import re
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from db import supabase
from security import (
    create_access_token,
    decode_access_token,
    hash_password,
    is_password_hash,
    verify_password,
)

app = FastAPI(title="API do Kanban")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)


# ---------- Modelos ----------
class CadastroUsuario(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nick: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(alias="pass", min_length=1, max_length=128)

    @field_validator("nick")
    @classmethod
    def validar_nick(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[\w.-]{3,32}", value, flags=re.UNICODE):
            raise ValueError("Use de 3 a 32 letras, números, ponto, hífen ou sublinhado")
        return value.casefold()

    @field_validator("email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Informe um e-mail válido")
        return value


class LoginUsuario(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identificador: str = Field(min_length=3, max_length=254)
    password: str = Field(alias="pass", min_length=1, max_length=128)

    @field_validator("identificador")
    @classmethod
    def normalizar_identificador(cls, value: str) -> str:
        return value.strip().casefold()


class QuadroNovo(BaseModel):
    titulo: str


class ColunaNova(BaseModel):
    quadro_id: int
    titulo: str


class CartaoNovo(BaseModel):
    coluna_id: int
    titulo: str
    descricao: Optional[str] = None


class CartaoEdicao(BaseModel):
    titulo: Optional[str] = None
    descricao: Optional[str] = None


class CartaoMover(BaseModel):
    coluna_id: int
    posicao: int


# ---------- Autenticação ----------
def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _buscar_usuario(campo: str, valor: str, incluir_senha: bool = True):
    colunas = "id_user,nick,email,pass" if incluir_senha else "id_user,nick,email"
    consulta = supabase.table("usuarios").select(colunas)
    if campo == "id_user":
        consulta = consulta.eq("id_user", int(valor))
    else:
        consulta = consulta.ilike(campo, _escape_ilike(valor))
    resultado = consulta.limit(1).execute()
    return resultado.data[0] if resultado.data else None


def _resposta_autenticacao(usuario: dict) -> dict:
    return {
        "access_token": create_access_token(usuario["id_user"]),
        "token_type": "bearer",
        "usuario": {
            "id_user": usuario["id_user"],
            "nick": usuario["nick"],
            "email": usuario["email"],
        },
    }


def _validar_senha_usuario(usuario: dict, password: str) -> bool:
    senha_salva = usuario.get("pass")
    if not isinstance(senha_salva, str) or not verify_password(password, senha_salva):
        return False

    # Contas antigas com senha em texto simples são atualizadas no primeiro login.
    if not is_password_hash(senha_salva):
        supabase.table("usuarios").update({"pass": hash_password(password)}).eq(
            "id_user", usuario["id_user"]
        ).execute()
    return True


def obter_usuario_atual(
    credenciais: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if credenciais is None or credenciais.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        usuario_id = decode_access_token(credenciais.credentials)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Sessão inválida ou expirada",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario = _buscar_usuario("id_user", str(usuario_id), incluir_senha=False)
    if not usuario:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return usuario


@app.post("/auth/cadastro", status_code=201)
def cadastrar_usuario(dados: CadastroUsuario, response: Response):
    por_nick = _buscar_usuario("nick", dados.nick)
    por_email = _buscar_usuario("email", dados.email)

    if por_nick or por_email:
        if (
            por_nick
            and por_email
            and por_nick["id_user"] == por_email["id_user"]
            and _validar_senha_usuario(por_nick, dados.password)
        ):
            response.status_code = 200
            return _resposta_autenticacao(por_nick)
        raise HTTPException(
            status_code=409,
            detail="Não foi possível cadastrar com esses dados. Verifique-os ou use o login.",
        )

    if len(dados.password) < 8:
        raise HTTPException(status_code=422, detail="A senha deve ter pelo menos 8 caracteres")

    usuario = (
        supabase.table("usuarios")
        .insert(
            {
                "nick": dados.nick,
                "email": dados.email,
                "pass": hash_password(dados.password),
            }
        )
        .execute()
        .data
    )
    if not usuario:
        raise HTTPException(status_code=500, detail="Não foi possível concluir o cadastro")
    return _resposta_autenticacao(usuario[0])


@app.post("/auth/login")
def login_usuario(dados: LoginUsuario):
    campo = "email" if "@" in dados.identificador else "nick"
    usuario = _buscar_usuario(campo, dados.identificador)
    if not usuario or not _validar_senha_usuario(usuario, dados.password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return _resposta_autenticacao(usuario)


@app.get("/auth/me")
def usuario_logado(usuario: dict = Depends(obter_usuario_atual)):
    return usuario


# ---------- Acesso aos dados por usuário ----------
def _validar_quadro_do_usuario(quadro_id: int, usuario_id: int) -> dict:
    resultado = (
        supabase.table("quadros")
        .select("id,usuario_id")
        .eq("id", quadro_id)
        .eq("usuario_id", usuario_id)
        .limit(1)
        .execute()
    )
    if not resultado.data:
        raise HTTPException(status_code=404, detail="Quadro não encontrado")
    return resultado.data[0]


def _validar_coluna_do_usuario(coluna_id: int, usuario_id: int) -> dict:
    resultado = (
        supabase.table("colunas")
        .select("id,quadro_id")
        .eq("id", coluna_id)
        .limit(1)
        .execute()
    )
    if not resultado.data:
        raise HTTPException(status_code=404, detail="Coluna não encontrada")
    coluna = resultado.data[0]
    _validar_quadro_do_usuario(coluna["quadro_id"], usuario_id)
    return coluna


def _validar_cartao_do_usuario(cartao_id: int, usuario_id: int) -> dict:
    resultado = (
        supabase.table("cartoes")
        .select("id,coluna_id")
        .eq("id", cartao_id)
        .limit(1)
        .execute()
    )
    if not resultado.data:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    cartao = resultado.data[0]
    _validar_coluna_do_usuario(cartao["coluna_id"], usuario_id)
    return cartao


# ---------- Rotas ----------
@app.get("/status")
def status():
    return {"status": "API do Kanban no ar"}


# QUADROS
@app.get("/quadros")
def listar_quadros(usuario: dict = Depends(obter_usuario_atual)):
    resposta = (
        supabase.table("quadros")
        .select("*")
        .eq("usuario_id", usuario["id_user"])
        .order("id")
        .execute()
    )
    return resposta.data


@app.post("/quadros", status_code=201)
def criar_quadro(dados: QuadroNovo, usuario: dict = Depends(obter_usuario_atual)):
    quadro = (
        supabase.table("quadros")
        .insert({"usuario_id": usuario["id_user"], "titulo": dados.titulo})
        .execute()
        .data[0]
    )
    colunas = [
        {"quadro_id": quadro["id"], "titulo": titulo, "posicao": i}
        for i, titulo in enumerate(["A fazer", "Em andamento", "Concluído"])
    ]
    supabase.table("colunas").insert(colunas).execute()
    return quadro


@app.get("/quadros/{quadro_id}")
def obter_quadro(quadro_id: int, usuario: dict = Depends(obter_usuario_atual)):
    _validar_quadro_do_usuario(quadro_id, usuario["id_user"])
    resposta = (
        supabase.table("quadros")
        .select("*, colunas(*, cartoes(*))")
        .eq("id", quadro_id)
        .execute()
    )
    quadro = resposta.data[0]
    quadro["colunas"].sort(key=lambda c: c["posicao"])
    for coluna in quadro["colunas"]:
        coluna["cartoes"].sort(key=lambda c: c["posicao"])
    return quadro


# COLUNAS
@app.post("/colunas", status_code=201)
def criar_coluna(dados: ColunaNova, usuario: dict = Depends(obter_usuario_atual)):
    _validar_quadro_do_usuario(dados.quadro_id, usuario["id_user"])
    ultima = (
        supabase.table("colunas")
        .select("posicao")
        .eq("quadro_id", dados.quadro_id)
        .order("posicao", desc=True)
        .limit(1)
        .execute()
        .data
    )
    posicao = ultima[0]["posicao"] + 1 if ultima else 0
    resposta = (
        supabase.table("colunas")
        .insert(
            {"quadro_id": dados.quadro_id, "titulo": dados.titulo, "posicao": posicao}
        )
        .execute()
    )
    return resposta.data[0]


# CARTÕES
@app.get("/colunas/{coluna_id}/cartoes")
def listar_cartoes(coluna_id: int, usuario: dict = Depends(obter_usuario_atual)):
    _validar_coluna_do_usuario(coluna_id, usuario["id_user"])
    resposta = (
        supabase.table("cartoes")
        .select("*")
        .eq("coluna_id", coluna_id)
        .order("posicao")
        .execute()
    )
    return resposta.data


@app.post("/cartoes", status_code=201)
def criar_cartao(dados: CartaoNovo, usuario: dict = Depends(obter_usuario_atual)):
    _validar_coluna_do_usuario(dados.coluna_id, usuario["id_user"])
    ultimo = (
        supabase.table("cartoes")
        .select("posicao")
        .eq("coluna_id", dados.coluna_id)
        .order("posicao", desc=True)
        .limit(1)
        .execute()
        .data
    )
    posicao = ultimo[0]["posicao"] + 1 if ultimo else 0
    resposta = (
        supabase.table("cartoes")
        .insert(
            {
                "coluna_id": dados.coluna_id,
                "titulo": dados.titulo,
                "descricao": dados.descricao,
                "posicao": posicao,
            }
        )
        .execute()
    )
    return resposta.data[0]


@app.patch("/cartoes/{cartao_id}")
def editar_cartao(
    cartao_id: int,
    dados: CartaoEdicao,
    usuario: dict = Depends(obter_usuario_atual),
):
    _validar_cartao_do_usuario(cartao_id, usuario["id_user"])
    campos = dados.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    resposta = supabase.table("cartoes").update(campos).eq("id", cartao_id).execute()
    if not resposta.data:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return resposta.data[0]


@app.patch("/cartoes/{cartao_id}/mover")
def mover_cartao(
    cartao_id: int,
    dados: CartaoMover,
    usuario: dict = Depends(obter_usuario_atual),
):
    _validar_cartao_do_usuario(cartao_id, usuario["id_user"])
    _validar_coluna_do_usuario(dados.coluna_id, usuario["id_user"])

    afetados = (
        supabase.table("cartoes")
        .select("id,posicao")
        .eq("coluna_id", dados.coluna_id)
        .gte("posicao", dados.posicao)
        .neq("id", cartao_id)
        .execute()
        .data
    )
    for cartao in afetados:
        supabase.table("cartoes").update(
            {"posicao": cartao["posicao"] + 1}
        ).eq("id", cartao["id"]).execute()

    resposta = (
        supabase.table("cartoes")
        .update({"coluna_id": dados.coluna_id, "posicao": dados.posicao})
        .eq("id", cartao_id)
        .execute()
    )
    return resposta.data[0]


@app.delete("/cartoes/{cartao_id}", status_code=204)
def excluir_cartao(cartao_id: int, usuario: dict = Depends(obter_usuario_atual)):
    _validar_cartao_do_usuario(cartao_id, usuario["id_user"])
    supabase.table("cartoes").delete().eq("id", cartao_id).execute()


@app.get("/assets/bolas_verdes_loop_suave.gif", include_in_schema=False)
def background_animation():
    return FileResponse("assets/bolas_verdes_loop_suave.gif", media_type="image/gif")


app.mount("/", StaticFiles(directory="front-endev", html=True), name="frontend")

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import supabase
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="API do Kanban")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USUARIO_ID = 1  # troque pelo id do usuário de teste, se for diferente


# ---------- Modelos (formato dos dados que a API recebe) ----------
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


# ---------- Rotas ----------
@app.get("/status")
def status():
    return {"status": "API do Kanban no ar"}


# QUADROS
@app.get("/quadros")
def listar_quadros():
    resposta = (
        supabase.table("quadros")
        .select("*")
        .eq("usuario_id", USUARIO_ID)
        .order("id")
        .execute()
    )
    return resposta.data


@app.post("/quadros", status_code=201)
def criar_quadro(dados: QuadroNovo):
    quadro = (
        supabase.table("quadros")
        .insert({"usuario_id": USUARIO_ID, "titulo": dados.titulo})
        .execute()
        .data[0]
    )
    # já cria as 3 colunas padrão
    colunas = [
        {"quadro_id": quadro["id"], "titulo": titulo, "posicao": i}
        for i, titulo in enumerate(["A fazer", "Em andamento", "Concluído"])
    ]
    supabase.table("colunas").insert(colunas).execute()
    return quadro


@app.get("/quadros/{quadro_id}")
def obter_quadro(quadro_id: int):
    resposta = (
        supabase.table("quadros")
        .select("*, colunas(*, cartoes(*))")
        .eq("id", quadro_id)
        .execute()
    )
    if not resposta.data:
        raise HTTPException(status_code=404, detail="Quadro não encontrado")

    quadro = resposta.data[0]
    quadro["colunas"].sort(key=lambda c: c["posicao"])
    for coluna in quadro["colunas"]:
        coluna["cartoes"].sort(key=lambda c: c["posicao"])
    return quadro


# COLUNAS
@app.post("/colunas", status_code=201)
def criar_coluna(dados: ColunaNova):
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
        .insert({"quadro_id": dados.quadro_id, "titulo": dados.titulo, "posicao": posicao})
        .execute()
    )
    return resposta.data[0]


# CARTÕES
@app.get("/colunas/{coluna_id}/cartoes")
def listar_cartoes(coluna_id: int):
    resposta = (
        supabase.table("cartoes")
        .select("*")
        .eq("coluna_id", coluna_id)
        .order("posicao")
        .execute()
    )
    return resposta.data


@app.post("/cartoes", status_code=201)
def criar_cartao(dados: CartaoNovo):
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
        .insert({
            "coluna_id": dados.coluna_id,
            "titulo": dados.titulo,
            "descricao": dados.descricao,
            "posicao": posicao,
        })
        .execute()
    )
    return resposta.data[0]


@app.patch("/cartoes/{cartao_id}")
def editar_cartao(cartao_id: int, dados: CartaoEdicao):
    campos = dados.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    resposta = supabase.table("cartoes").update(campos).eq("id", cartao_id).execute()
    if not resposta.data:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return resposta.data[0]


@app.patch("/cartoes/{cartao_id}/mover")
def mover_cartao(cartao_id: int, dados: CartaoMover):
    existe = supabase.table("cartoes").select("id").eq("id", cartao_id).execute().data
    if not existe:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    # abre espaço no destino: empurra uma posição para baixo quem está na frente
    afetados = (
        supabase.table("cartoes")
        .select("id, posicao")
        .eq("coluna_id", dados.coluna_id)
        .gte("posicao", dados.posicao)
        .neq("id", cartao_id)
        .execute()
        .data
    )
    for c in afetados:
        supabase.table("cartoes").update({"posicao": c["posicao"] + 1}).eq("id", c["id"]).execute()

    resposta = (
        supabase.table("cartoes")
        .update({"coluna_id": dados.coluna_id, "posicao": dados.posicao})
        .eq("id", cartao_id)
        .execute()
    )
    return resposta.data[0]


@app.delete("/cartoes/{cartao_id}", status_code=204)
def excluir_cartao(cartao_id: int):
    supabase.table("cartoes").delete().eq("id", cartao_id).execute()

app.mount("/", StaticFiles(directory="frontendev", html=True), name="frontend")
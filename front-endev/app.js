const API = "http://127.0.0.1:8000";
const telaLogin = document.getElementById("tela-login");
const formularioLogin = document.getElementById("form-login");
const mensagemLogin = document.getElementById("mensagem-login");
const botaoEntrar = document.getElementById("botao-entrar");
const appKanban = document.getElementById("app-kanban");
const seletor = document.getElementById("seletor-quadro");
const quadroEl = document.getElementById("quadro");
let accessToken = null;

async function api(caminho, metodo = "GET", corpo) {
  const headers = {};
  if (corpo !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const resp = await fetch(API + caminho, {
    method: metodo,
    headers,
    body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
  });
  if (!resp.ok) {
    const erro = await resp.json().catch(() => null);
    throw new Error(erro?.detail || `Erro ${resp.status}`);
  }
  return resp.status === 204 ? null : resp.json();
}

async function carregarQuadros(selecionarId) {
  const quadros = await api("/quadros");
  seletor.innerHTML = "";
  quadros.forEach((q) => seletor.add(new Option(q.titulo, q.id)));
  if (quadros.length) {
    seletor.value = selecionarId ?? quadros[0].id;
    await carregarQuadro(seletor.value);
  } else {
    quadroEl.innerHTML = '<p class="vazio">Nenhum quadro ainda. Clique em "Novo quadro" para começar.</p>';
  }
}

async function carregarQuadro(id) {
  const quadro = await api("/quadros/" + id);
  quadroEl.innerHTML = "";
  quadro.colunas.forEach((col) => quadroEl.append(criarColuna(col)));
}

function criarColuna(col) {
  const secao = document.createElement("section");
  secao.className = "coluna";

  const titulo = document.createElement("h2");
  titulo.textContent = col.titulo;

  const lista = document.createElement("div");
  lista.className = "lista";
  lista.dataset.id = col.id;
  col.cartoes.forEach((c) => lista.append(criarCartao(c)));

  const botao = document.createElement("button");
  botao.className = "adicionar";
  botao.textContent = "+ Adicionar cartão";
  botao.onclick = async () => {
    const t = prompt("Título do cartão:");
    if (t && t.trim()) {
      await api("/cartoes", "POST", { coluna_id: col.id, titulo: t.trim() });
      await carregarQuadro(seletor.value);
    }
  };

  new Sortable(lista, {
    group: "kanban",
    animation: 150,
    ghostClass: "fantasma",
    onEnd: async (evt) => {
      try {
        await api(`/cartoes/${evt.item.dataset.id}/mover`, "PATCH", {
          coluna_id: Number(evt.to.dataset.id),
          posicao: evt.newIndex,
        });
      } catch (e) {
        await carregarQuadro(seletor.value);
      }
    },
  });

  secao.append(titulo, lista, botao);
  return secao;
}

function criarCartao(c) {
  const el = document.createElement("div");
  el.className = "cartao";
  el.dataset.id = c.id;

  const texto = document.createElement("span");
  texto.textContent = c.titulo;
  texto.title = "Clique para editar";
  texto.onclick = async () => {
    const t = prompt("Novo título:", texto.textContent);
    if (t && t.trim()) {
      await api("/cartoes/" + c.id, "PATCH", { titulo: t.trim() });
      texto.textContent = t.trim();
    }
  };

  const excluir = document.createElement("button");
  excluir.className = "excluir";
  excluir.textContent = "×";
  excluir.title = "Excluir cartão";
  excluir.onclick = async () => {
    if (confirm("Excluir este cartão?")) {
      await api("/cartoes/" + c.id, "DELETE");
      el.remove();
    }
  };

  el.append(texto, excluir);
  return el;
}

formularioLogin.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  mensagemLogin.textContent = "";
  botaoEntrar.disabled = true;

  const dados = new FormData(formularioLogin);
  try {
    const resposta = await fetch(API + "/auth/cadastro", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nick: dados.get("nick"),
        email: dados.get("email"),
        pass: dados.get("pass"),
      }),
    });
    const resultado = await resposta.json().catch(() => null);
    if (!resposta.ok) {
      throw new Error(resultado?.detail || "Não foi possível entrar. Confira os dados e tente novamente.");
    }
    if (!resultado?.access_token) {
      throw new Error("A API não retornou uma sessão de acesso.");
    }

    accessToken = resultado.access_token;
    telaLogin.hidden = true;
    appKanban.hidden = false;
    try {
      await carregarQuadros();
    } catch (erro) {
      appKanban.hidden = true;
      telaLogin.hidden = false;
      accessToken = null;
      throw erro;
    }
  } catch (erro) {
    mensagemLogin.textContent = erro.message || "Não foi possível entrar. Tente novamente.";
  } finally {
    botaoEntrar.disabled = false;
  }
});

document.getElementById("novo-quadro").onclick = async () => {
  const t = prompt("Nome do quadro:");
  if (t && t.trim()) {
    const novo = await api("/quadros", "POST", { titulo: t.trim() });
    await carregarQuadros(novo.id);
  }
};

seletor.onchange = () => carregarQuadro(seletor.value);

window.addEventListener("unhandledrejection", () =>
  alert("Não foi possível falar com a API. Verifique sua conexão com o servidor.")
);

const API = "";
const seletor = document.getElementById("seletor-quadro");
const quadroEl = document.getElementById("quadro");

// Função única para falar com a API
async function api(caminho, metodo = "GET", corpo) {
  const resp = await fetch(API + caminho, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (!resp.ok) throw new Error("Erro " + resp.status);
  return resp.status === 204 ? null : resp.json();
}

async function carregarQuadros(selecionarId) {
  const quadros = await api("/quadros");
  seletor.innerHTML = "";
  quadros.forEach((q) => seletor.add(new Option(q.titulo, q.id)));
  if (quadros.length) {
    seletor.value = selecionarId ?? quadros[0].id;
    carregarQuadro(seletor.value);
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
      carregarQuadro(seletor.value);
    }
  };

  // Arrastar e soltar: ao soltar, avisa a API a nova coluna e posição
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
        carregarQuadro(seletor.value); // desfaz na tela se a API falhar
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

document.getElementById("novo-quadro").onclick = async () => {
  const t = prompt("Nome do quadro:");
  if (t && t.trim()) {
    const novo = await api("/quadros", "POST", { titulo: t.trim() });
    carregarQuadros(novo.id);
  }
};
seletor.onchange = () => carregarQuadro(seletor.value);

window.addEventListener("unhandledrejection", () =>
  alert("Não foi possível falar com a API. O uvicorn está rodando?")
);

carregarQuadros();
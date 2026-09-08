# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Um framework de agente long-horizon portável construído sobre o Claude Agent SDK.</p>

<p class="fl-hero__sub">Sem sacrificar as capacidades do Claude Code, ele o transforma num agente dedicado que você pode levar consigo, cuja interação você pode customizar, e que roda por dias a fio.
O agente na main thread só toma decisões; todo o trabalho braçal é delegado a subagents; o requisito é esclarecido antes de começar, e se algo ficou pronto ou não é decidido por outro papel.
Trocar de máquina não muda o comportamento — ele não lê as configurações da máquina hospedeira e traz as próprias credenciais.</p>

[Início rápido](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>custo de uma run</span></div>
<div class="fl-stat"><b>10.4 horas</b><span>rodando ininterruptamente, retomando sozinho após uma queda de rede</span></div>
<div class="fl-stat"><b>185.9K</b><span>pico de contexto na main thread, sem nenhum compact ao longo de todo o percurso</span></div>
<div class="fl-stat"><b>94.8 %</b><span>dos caracteres de corpo caem nos subagents</span></div>
</div>

Os quatro números vêm de [HT001](cases/ht001.md) — a run em que um agente escreveu do zero um IDE de terminal sob o flower.

## Instalação {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Encontra automaticamente `uv` / `pipx` / `pip` e instala o comando `flower`. Basta ter Python ≥ 3.10, sem precisar instalar Node
nem o Claude Code CLI. Depois de instalar, faça `cd` para qualquer diretório de projeto e digite `flower`: na primeira vez ele pede sua API key
ou o endereço do gateway; configura uma vez, salva em `~/.config/flower/.env`, e vale em todo lugar; se a máquina já tem o Claude Code instalado e configurado,
ele pega aquele token emprestado direto, sem nem perguntar. Passos completos e resolução de problemas em [Instalação](getting-started/install.md).

## Ele barra quatro tipos de falha por você {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Medo de o resultado não ser o que você queria — antes de começar, há um papel que só faz perguntas, não age, e pergunta até tudo ficar claro, congelando o requisito num documento
que cada passo posterior lê para começar.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Medo de ele dizer que terminou quando na verdade não terminou — ao fim de cada rodada de trabalho, outro papel julga uma vez de forma independente; se atingido, segue adiante, se não, devolve,
e se este ambiente não consegue verificar, ele para e pergunta a uma pessoa.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Medo de rodar por horas, cair e ter que recomeçar do zero — digite `flower` de novo no mesmo diretório e ele retoma o progresso da última vez, seja processo morto,
seja máquina reiniciada, e você não precisa lembrar de nenhum id.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Medo de o contexto encher e ser esmagado num resumo — a sessão atual escreve por si um handoff document que uma pessoa consegue ler e editar, e uma nova sessão assume,
sem precisar de compact.
</div>

</div>

## Por que ele é "long-horizon" {#长程}

O [coordinator](reference/glossary.md#协调者) na main thread carrega apenas decisão, não tem acesso a `Write` nem `Edit` —
escrever código, rodar testes, buscar informação, tudo é delegado a [subagents](reference/glossary.md#subagent);
o tentar-e-errar do subagent entra em **outra** transcript, e a main thread só recebe um relatório de no máximo 30 linhas.
Naquela run de 10.4 horas do HT001, **94.8 % dos caracteres de corpo caíram nos subagents**,
e das 1.893 chamadas de ferramenta braçais só 32 entraram no campo de visão do coordinator.
Por isso a main thread levou 70 rodadas para chegar a 185.9K, sem que nenhum compact ocorresse ao longo de todo o percurso — como essa camada foi feita, e o que são as outras três,
veja [Economia de contexto](guide/context.md).

## Já rodou de verdade {#真的跑过}

- **[HT001](cases/ht001.md)** — escrever do zero um IDE de terminal. $171.62 / 10.4 horas /
  contexto da main thread subindo a 185.9K, entregando 12.212 linhas de código de produto, com uma queda de rede no meio, retomando e terminando por si.
- **[HT002](cases/ht002.md)** — instalá-lo e rodá-lo no macOS. $38.24 / cerca de 1 hora, primeira vez com goal guard;
  o programa de fato rodou, mas o verdict foi **impossível de atingir**, e a questão veio à tona para uma pessoa.

Ambas as páginas descrevem os pontos que não se sustentam: no HT001 o agente errou um item da própria aceitação,
e no HT002 transformou `git clone && make && ./cppide` numa hora inteira. Cada número pode ser recalculado em `runs/manifest.json`
e em `sessions.db` — este é o registro bruto, não propaganda.

## Por onde começar {#从哪读起}

- **Quer rodar já** — [Início rápido](getting-started/quickstart.md): primeiro gaste alguns centavos para validar a credencial,
  depois rode um workflow de três passos, sem código.
- **Quer entender os conceitos primeiro** — [Conceitos essenciais](getting-started/concepts.md): run, step, session, os cinco papéis,
  tudo dito de uma vez em cinco minutos.
- **Quer integrar ao seu próprio código** — [Python API](reference/api.md): `Runtime`, `Step`, as cinco fábricas de papéis,
  as assinaturas e valores padrão dos 62 símbolos públicos.

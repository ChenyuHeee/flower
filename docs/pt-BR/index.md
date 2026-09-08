# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Framework de agent long-horizon portátil, construído sobre o Claude Agent SDK.</p>

<p class="fl-hero__sub">Sem abrir mão do que o Claude Code sabe fazer, ele vira um agent especializado que você leva junto, cuja interação você customiza e que roda por dias.
O agent na main thread só decide; todo trabalho braçal vai para subagents. O requisito é esclarecido antes de começar, e se algo ficou pronto ou não quem julga é outro papel.
Troque de máquina e o comportamento é o mesmo — ele não lê as configurações do host, traz as próprias credenciais.</p>

[Início rápido](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>custo de uma run</span></div>
<div class="fl-stat"><b>10.4 horas</b><span>contínuas, retomou sozinha após queda de rede</span></div>
<div class="fl-stat"><b>185.9K</b><span>pico de contexto na main thread, sem nenhum compact</span></div>
<div class="fl-stat"><b>94.8%</b><span>dos caracteres de corpo caíram nos subagents</span></div>
</div>

Os quatro números vêm de [HT001](cases/ht001.md) — a run em que um agent escreveu um IDE de terminal do zero sob o flower.

## Instala com um comando, sem Node {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

O script procura `uv` / `pipx` / `pip` automaticamente e instala o comando `flower`; basta Python ≥ 3.10,
e nem o Claude Code CLI é necessário. Depois de instalar, faça `cd` para qualquer diretório de projeto e digite `flower`: na primeira vez ele pede a API key
ou o endereço do gateway, você configura uma vez, fica salvo em `~/.config/flower/.env` e vale em todo lugar; se a máquina já tem o Claude Code instalado e configurado,
ele pega aquele token emprestado direto, sem perguntar nada. Passos completos e resolução de problemas em [Instalação](getting-started/install.md).

## Ele barra quatro classes de falha por você {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Medo de construir o que não era o pedido — antes de pôr a mão na massa há um papel que só pergunta, não age, até tudo ficar claro, e congela o requisito em um documento
que cada passo seguinte lê para abrir.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Medo de ouvir "terminei" quando não terminou — ao fim de cada rodada de trabalho outro papel julga de forma independente: atingiu, segue adiante; não atingiu, volta;
não dá para verificar neste ambiente, para e pergunta a um humano.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Medo de rodar horas, quebrar e recomeçar do zero — digite `flower` de novo no mesmo diretório e ele retoma o progresso anterior; vale também se o processo levou kill
ou a máquina reiniciou, e você não precisa memorizar id nenhum.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Medo de o contexto encher e virar um resumo espremido — a sessão atual escreve ela mesma um handoff document legível e editável por humanos, e uma sessão nova assume,
sem compact.
</div>

</div>

## Por que ele é "long-horizon" {#长程}

O [coordinator](reference/glossary.md#协调者) na main thread carrega só decisão, não recebe `Write` nem `Edit` —
escrever código, rodar testes, pesquisar, tudo vai para [subagents](reference/glossary.md#subagent),
e a tentativa e erro do subagent entra em **outro** transcript; a main thread só recebe um relatório de no máximo 30 linhas.
Naquela run de 10.4 horas do HT001, **94.8% dos caracteres de corpo caíram nos subagents**,
e das 1,893 chamadas de ferramenta que puseram a mão na massa apenas 32 entraram no campo de visão do coordinator.
Por isso a main thread só chegou a 185.9K depois de 70 rodadas e nunca sofreu compact — como essa camada é feita e quais são as outras três,
veja [Economia de contexto](guide/context.md).

## Registros brutos de duas maratonas reais {#真的跑过}

- **[HT001](cases/ht001.md)** — escrever um IDE de terminal do zero. $171.62 / 10.4 horas /
  contexto da main thread subiu até 185.9K, entregou 12,212 linhas de código de produto, caiu a rede uma vez no meio e ele retomou sozinho até o fim.
- **[HT002](cases/ht002.md)** — instalar e pôr para rodar no macOS. $38.24 / cerca de 1 hora, primeira vez com goal guard;
  o programa de fato subiu, e mesmo assim o verdict foi **não atingido**, e a questão veio à tona para um humano.

As duas páginas escrevem também o que não se sustenta: no HT001 o agent errou uma condição na própria verificação de aceite,
e no HT002 `git clone && make && ./cppide` virou uma hora de trabalho. Cada número pode ser recalculado em `runs/manifest.json`
e `sessions.db` — é registro, não propaganda.

## Por onde começar a ler {#从哪读起}

- **Quer rodar agora** — [Início rápido](getting-started/quickstart.md): três comandos para colocar de pé,
  e depois ele te ensina a ler o que passou rolando na tela.
- **Quer entender os conceitos primeiro** — [Conceitos centrais](getting-started/concepts.md): run, step, session, os cinco papéis,
  tudo dito de uma vez em cinco minutos.
- **Quer plugar no seu próprio código** — [Python API](reference/api.md): `Runtime`, `Step`, as cinco fábricas de papéis,
  assinaturas e valores padrão dos 62 símbolos públicos.

# Fiscalização Minerária — Sistema Confea/Crea

MVP em Streamlit para apoiar a fiscalização remota de empresas de mineração a partir de dados públicos da ANM. O projeto foi desenhado para uso por diferentes Regionais: a base minerária pública é comum, enquanto os dados de registro, ART e responsáveis técnicos do Crea devem ser carregados somente por fonte autorizada de cada Regional.

## O que já funciona

- Importação de bases ANM em CSV, XLSX ou Parquet.
- Exclusão automática de linhas sem CNPJ válido, sem descartar empresas duplicadas em processos diferentes.
- Consolidação de empreendimentos por CNPJ.
- Filtros por Regional/UF, município, texto e prioridade.
- Painel com empresas, processos, municípios e fila de prioridade.
- Comparação opcional com arquivo interno do Crea.
- Exportação da fila de fiscalização em CSV.
- Base legal e links oficiais.
- Checklist de fiscalização remota.
- Atualização automática de CFEM e Cadastro Mineiro pelo próprio painel.
- Filtros operacionais por UF/Regional e município.

## Atualização automática da ANM

O script `scripts/update_anm.py` descobre arquivos publicados nas páginas dos conjuntos da ANM, baixa os snapshots para `data/anm/` e grava `manifest.json` com data, URL, tamanho e SHA-256. Ele pode ser executado manualmente:

No aplicativo, o fiscal não precisa procurar planilhas: o botão **Atualizar dados públicos da ANM** tenta buscar os recursos de CFEM e Cadastro Mineiro diretamente. Como o catálogo `dados.gov.br` carrega o conteúdo por JavaScript e pode proteger sua API, a tela também aceita links diretos dos arquivos como fallback administrativo. Esses links devem ser configurados uma única vez, não por fiscal a cada consulta.

Os recursos atualmente identificados no catálogo são:

- Licenciamento: `https://dadosabertos.anm.gov.br/SCM/Licenciamento.csv`
- CFEM 2022–2026: `https://dadosabertos.anm.gov.br/CFEM/CFEM_Arrecadacao_2022_2026.csv`

### Certificado TLS da ANM

Em algumas instalações do Python/Windows, o servidor `dadosabertos.anm.gov.br` apresenta uma cadeia de certificado que não é reconhecida pelo pacote de certificados local, embora o navegador consiga acessar o arquivo. O cliente tenta primeiro HTTPS com validação normal. Se ocorrer essa falha, ele usa fallback somente para o host público `dadosabertos.anm.gov.br` e mostra um aviso no painel. Não desabilite a validação para outros domínios. A correção definitiva é a ANM atualizar a cadeia do certificado ou a máquina receber a CA intermediária correta.

```bash
pip install -r requirements.txt
python scripts/update_anm.py --dry-run
python scripts/update_anm.py
```

O workflow `.github/workflows/update-anm.yml` executa o script diariamente e também pode ser iniciado manualmente em **Actions > Atualizar dados públicos da ANM > Run workflow**. Os arquivos são publicados como artefato por 30 dias. Eles não são commitados no repositório, porque bases geográficas e históricas podem ser grandes. Se a ANM alterar os links dos arquivos, use as variáveis `ANM_URL_CADASTRO_MINEIRO`, `ANM_URL_AMB`, `ANM_URL_CFEM`, `ANM_URL_SIGMINE` ou `ANM_URL_SIGBM` no workflow/repositório.

## GitHub e Streamlit Community Cloud

1. Crie um repositório privado no GitHub, por exemplo `fiscalizacao-mineraria-streamlit`.
2. Na pasta do projeto, inicialize e envie o código:

```bash
git init
git add .
git commit -m "feat: MVP de fiscalização minerária"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/fiscalizacao-mineraria-streamlit.git
git push -u origin main
```

3. Acesse `https://share.streamlit.io`, conecte sua conta GitHub e selecione **Create app**.
4. Escolha o repositório, a branch `main` e o arquivo `app.py`. Em **Advanced settings**, selecione Python 3.12 se necessário e configure apenas secrets que realmente existirem.
5. Clique em **Deploy**. Alterações enviadas à branch selecionada serão refletidas automaticamente no aplicativo.

Não coloque bases internas, tokens, senhas ou arquivos de Crea no Git. Use o mecanismo **Secrets** do Streamlit para credenciais e, para dados privados, prefira banco ou armazenamento controlado. O workflow de download é independente do deploy: o primeiro atualiza o artefato; o segundo atualiza o aplicativo quando o código muda. Para o painel consumir os dados automaticamente, a próxima etapa é conectar o app a um banco/objeto privado ou gerar um CSV consolidado pequeno e versionado após validação.

## Como executar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No Streamlit Community Cloud, aponte o aplicativo para `app.py` e use este repositório do GitHub. Não coloque credenciais, bases internas ou dados pessoais no Git.

## Dados e cautelas

A ANM publica o Cadastro Mineiro, o Anuário Mineral Brasileiro, CFEM, SIGMINE, SIGBM e outros conjuntos por meio de seu portal de dados abertos. O formato e os endereços de download podem mudar; por isso, o MVP começa aceitando os arquivos oficiais baixados e deixa a automação de atualização como um adaptador separado.

O painel não autua automaticamente. “Sem registro localizado” significa que não houve correspondência na fonte carregada e deve gerar diligência, não conclusão automática de infração. A notificação e o auto de infração dependem de análise humana, competência territorial, enquadramento jurídico, confirmação da atividade e respeito ao contraditório.

## Próxima evolução

1. Adaptadores de download versionados para Cadastro Mineiro, AMB, CFEM, SIGMINE e SIGBM.
2. Banco PostgreSQL com histórico de snapshots, fonte, data de coleta e hash dos arquivos.
3. Login e segregação por Regional/Crea, com trilha de auditoria.
4. Integração autorizada de registros, ARTs e responsáveis técnicos.
5. Mapa geográfico de processos e empreendimentos.
6. Geração de minutas de diligência e notificações, sempre sujeitas à revisão do agente fiscal.
7. Módulo de fiscalização presencial com evidências, documentos, fotos e encaminhamento processual.

## Fontes oficiais

- ANM — bases de dados: https://www.gov.br/anm/pt-br/acesso-a-informacao/dados-abertos/bases-de-dados
- ANM — Cadastro Mineiro: https://www.gov.br/anm/pt-br/acesso-a-informacao/processos/consulta-a-processos/cadastro-mineiro
- Confea — fiscalização: https://www.confea.org.br/atuacao/fiscalizacao
- Resolução Confea nº 1.008/2004: https://normativos.confea.org.br/Ementas/Visualizar?id=548
- Lei nº 6.496/1977: https://www.planalto.gov.br/ccivil_03/leis/l6496.htm
- Cooperação Confea–ANM: https://www.confea.org.br/confea-e-agencia-nacional-de-mineracao-se-unem-no-combate-informalidade
- Deploy no Streamlit Community Cloud: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Organização de arquivos no Streamlit Community Cloud: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
- GitHub Actions — agendamento: https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions

## Certificado TLS da ANM (remover o aviso de fallback)

O servidor `dadosabertos.anm.gov.br` não envia o certificado intermediário, então o Python não consegue
verificar a conexão. Para gerar a cadeia (uma vez, na sua máquina):

```
pip install cryptography
python scripts/fetch_anm_chain.py   # cobre dadosabertos.anm.gov.br e app.anm.gov.br
```

Isso cria `certs/anm_chain.pem`. Suba esse arquivo no GitHub: o app e o workflow passam a verificar o
certificado normalmente e o aviso deixa de aparecer. Sem o arquivo, o fallback restrito ao domínio da ANM continua valendo.


## Mapa (Leaflet/OpenStreetMap)

Página **Mapa**: (1) baixe o SIGMINE da UF (`https://app.anm.gov.br/dadosabertos/SIGMINE/PROCESSOS_MINERARIOS/{UF}.zip`)
ou envie o shapefile .zip; (2) baixe os limites municipais do IBGE ou envie um KML/KMZ dos municípios.
Pontos por prioridade, municípios coloridos pelo nº de empresas Alta e exportação do mapa em HTML.

from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from sigmine_utils import read_sigmine, pontos_empresas
import copy
import streamlit.components.v1 as components
from geo_utils import ler_kml, stats_municipio, montar_mapa
from loader import UFS, UF_INFO, PASSOS, executar_passo, limpar_cache
from data_utils import CONFIG, read_uploaded, normalize, enrich, company_summary, export_frames

st.set_page_config(page_title=CONFIG['app']['title'], page_icon='⛏️', layout='wide')

if 'minerios' not in st.session_state: st.session_state.minerios = pd.DataFrame()
if 'crea' not in st.session_state: st.session_state.crea = pd.DataFrame()
if 'sigmine' not in st.session_state: st.session_state.sigmine = pd.DataFrame()
if 'municipios' not in st.session_state: st.session_state.municipios = None
if 'carga' not in st.session_state: st.session_state.carga = {}        # passo -> (ok, mensagem)
if 'frames' not in st.session_state: st.session_state.frames = {}      # passo -> DataFrame (CFEM)
if 'titulares' not in st.session_state: st.session_state.titulares = pd.DataFrame()   # cnpj -> razão social
if 'uf_ativa' not in st.session_state: st.session_state.uf_ativa = None
if 'tls_fallback' not in st.session_state: st.session_state.tls_fallback = False


def sem_valores(df):
    """Oculta as colunas de valor por ano (CFEM 2022, CFEM 2023...), mantendo 'anos_cfem'."""
    return df.drop(columns=[c for c in df.columns if str(c).startswith('CFEM ')])

def mostrar_html(html, altura):
    """st.iframe (Streamlit recente); components.html nas versões antigas."""
    if hasattr(st, 'iframe'):
        st.iframe(html, height=altura)
    else:
        components.html(html, height=altura, scrolling=False)


def zerar_carga():
    st.session_state.update(frames={}, carga={}, sigmine=pd.DataFrame(), municipios=None, minerios=pd.DataFrame(), titulares=pd.DataFrame(), tls_fallback=False)


def guardar(passo, dados):
    if passo == 'cfem':
        st.session_state.frames['cfem'] = dados
        st.session_state.minerios = dados
    elif passo == 'cadastro_mineiro':
        st.session_state.titulares = dados
    elif passo == 'sigmine':
        st.session_state.sigmine = dados
    elif passo == 'municipios':
        st.session_state.municipios = dados


with st.sidebar:
    st.title('Fiscalização Minerária')
    st.caption('Sistema Confea/Crea • ANM')
    _padrao = CONFIG['app'].get('default_uf', 'MS')
    uf = st.selectbox('Estado', UFS, index=UFS.index(_padrao) if _padrao in UFS else 0,
                      help='Ao escolher o estado, o app baixa CFEM, Cadastro Mineiro, SIGMINE e limites municipais.')
    box_lista = st.container()
    box_botoes = st.container()
    with box_botoes:
        _falhas = [p for p, (ok, _) in st.session_state.carga.items() if not ok]
        tentar = st.button('Tentar novamente o que falhou', use_container_width=True) if _falhas else False
        recarregar = st.button('Recarregar tudo (ignorar cache)', use_container_width=True)
    st.divider()
    page = st.radio('Navegação', ['Painel', 'Empresas', 'Mapa', 'Importação de dados', 'Legislação e fontes', 'Checklist remoto'])
    st.caption('A base pública é um apoio à triagem. A confirmação de infração exige análise do agente fiscal.')
    st.divider()

# ---- carga automática: troca de estado, recarga total ou retentativa dos passos com falha
_passos = []
if st.session_state.uf_ativa != uf:
    zerar_carga(); st.session_state.uf_ativa = uf; _passos = list(PASSOS)
elif recarregar:
    limpar_cache(); zerar_carga(); _passos = list(PASSOS)
elif tentar:
    _passos = list(_falhas)
    if 'cfem' in _passos and 'cadastro_mineiro' not in _passos:
        _passos.append('cadastro_mineiro')
    _passos = [p for p in PASSOS if p in _passos]
if _passos:
    with st.sidebar:
        with st.status(f'Carregando dados de {uf}...', expanded=True) as _st:
            for _p in _passos:
                st.write(f'⏳ {PASSOS[_p]}...')
                try:
                    _dados, _tls, _msg = executar_passo(_p, uf)
                    guardar(_p, _dados)
                    st.session_state.carga[_p] = (True, _msg)
                    st.session_state.tls_fallback = st.session_state.tls_fallback or _tls
                except Exception as exc:
                    st.session_state.carga[_p] = (False, str(exc)[:300])
            _ok = all(v[0] for v in st.session_state.carga.values())
            _st.update(label=f'Dados de {uf} ' + ('carregados' if _ok else 'carregados com falhas'), state='complete' if _ok else 'error', expanded=False)
        st.session_state.anm_updated = pd.Timestamp.now(tz='UTC').isoformat()
    st.rerun()

with box_lista:
    for _p, _nome in PASSOS.items():
        if _p in st.session_state.carga:
            _ok, _msg = st.session_state.carga[_p]
            st.caption(f"{'✅' if _ok else '❌'} **{_nome}** — {_msg}")
        else:
            st.caption(f'⏸️ **{_nome}** — não carregado')
    if st.session_state.tls_fallback:
        st.caption('⚠️ ANM acessada por fallback TLS restrito ao domínio da ANM. Gere `certs/anm_chain.pem` para verificação completa.')
    if st.session_state.get('anm_updated'):
        st.caption('Última atualização: ' + st.session_state.anm_updated[:19].replace('T', ' ') + ' UTC')

ufs = [uf]

base = enrich(st.session_state.minerios, st.session_state.crea)
if ufs and not base.empty: base = base[base.uf.isin(ufs)]
with st.sidebar:
    municipios = ['Todos'] + sorted(base.municipio[base.municipio.ne('')].dropna().unique().tolist()) if not base.empty else ['Todos']
    municipio = st.selectbox('Município', municipios)
if municipio != 'Todos' and not base.empty: base = base[base.municipio.eq(municipio)]
empresas = company_summary(base, st.session_state.titulares)
sem_ano = (not empresas.empty) and empresas['ultimo_ano_cfem'].isna().all()
ano_col = base['_ano_coluna'].iloc[0] if (not base.empty and '_ano_coluna' in base) else None


def aviso_ano():
    if sem_ano:
        st.warning('Coluna do ano de recolhimento da CFEM não identificada: a prioridade não considera anos. '
                   'Veja as colunas recebidas abaixo e ajuste os nomes em config.yaml (columns > ano).')
        with st.expander('Colunas recebidas da ANM'):
            st.write([c for c in st.session_state.minerios.columns if not str(c).startswith('_')])
    elif ano_col:
        st.caption(f'Ano de recolhimento da CFEM lido da coluna “{ano_col}”.')


if page == 'Importação de dados':
    st.header('Importação e atualização de dados')
    st.info('Os dados da ANM são carregados automaticamente ao escolher o estado (barra lateral). Esta página é o plano B: links diretos e upload manual. Depois de salvar links diretos, use “Recarregar tudo” na barra lateral.')
    st.subheader('Links diretos opcionais dos arquivos')
    st.caption('O catálogo dados.gov.br é dinâmico. Se a página não expuser automaticamente os CSVs, cole aqui os links diretos dos recursos, um por linha.')
    c0, c1 = st.columns(2)
    with c0:
        cfem_urls = st.text_area('Recursos CFEM', value='\n'.join(st.session_state.get('anm_direct_urls', {}).get('cfem', [])), height=100)
    with c1:
        cm_urls = st.text_area('Recursos Cadastro Mineiro', value='\n'.join(st.session_state.get('anm_direct_urls', {}).get('cadastro_mineiro', [])), height=100)
    if st.button('Salvar links diretos'):
        st.session_state.anm_direct_urls = {'cfem': [x.strip() for x in cfem_urls.splitlines() if x.strip()], 'cadastro_mineiro': [x.strip() for x in cm_urls.splitlines() if x.strip()]}
        st.success('Links salvos nesta sessão. Use “Recarregar tudo (ignorar cache)” na barra lateral.')
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader('ANM — mineração')
        up = st.file_uploader('CSV, XLSX ou Parquet', type=['csv','xlsx','xls','parquet'], key='anm_upload')
        if up and st.button('Carregar base ANM'):
            try:
                st.session_state.minerios = normalize(read_uploaded(up))
                st.success(f'{len(st.session_state.minerios):,} registros empresariais carregados.')
            except Exception as e: st.error(str(e))
    with c2:
        st.subheader('Crea — registros/ARTs')
        upc = st.file_uploader('Arquivo autorizado do Crea', type=['csv','xlsx','xls','parquet'], key='crea_upload')
        if upc and st.button('Carregar base Crea'):
            try:
                st.session_state.crea = normalize(read_uploaded(upc))
                st.success(f'{len(st.session_state.crea):,} registros carregados.')
            except Exception as e: st.error(str(e))
    st.divider()
    st.markdown('**Fontes oficiais de referência**')
    for name, url in CONFIG['sources'].items(): st.markdown(f'- [{name}]({url})')

elif page == 'Painel':
    st.header('Painel de inteligência fiscal')
    if base.empty:
        st.warning('Nenhum dado empresarial carregado. Use “Importação de dados” para carregar uma base oficial da ANM.')
    else:
        aviso_ano()
        a,b,c,d = st.columns(4)
        a.metric('Empresas', f'{len(empresas):,}')
        b.metric('Processos/linhas', f'{len(base):,}')
        c.metric('Municípios', f'{base.municipio.replace("", pd.NA).dropna().nunique():,}')
        d.metric('Prioridade alta', f'{(empresas.prioridade == "Alta").sum():,}')
        left, right = st.columns(2)
        with left:
            mun = empresas.groupby('municipio', dropna=False).size().reset_index(name='empresas').sort_values('empresas', ascending=False).head(20)
            st.plotly_chart(px.bar(mun, x='empresas', y='municipio', orientation='h', title='Empresas por município'), use_container_width=True)
        with right:
            pri = empresas.groupby('prioridade', dropna=False).size().reset_index(name='empresas')
            st.plotly_chart(px.pie(pri, names='prioridade', values='empresas', title='Distribuição de prioridade'), use_container_width=True)
        st.subheader('Fila para análise do agente fiscal')
        st.dataframe(sem_valores(empresas), use_container_width=True, hide_index=True)

elif page == 'Empresas':
    st.header('Empresas e empreendimentos')
    if empresas.empty: st.info('Carregue uma base para consultar empresas.')
    else:
        aviso_ano()
        q = st.text_input('Pesquisar por CNPJ, razão social, município ou substância')
        prioridades = st.multiselect('Prioridade', sorted(empresas.prioridade.dropna().unique()), default=sorted(empresas.prioridade.dropna().unique()))
        mostrar_valores = st.checkbox('Mostrar também o valor recolhido por ano (R$)', value=False)
        view = empresas[empresas.prioridade.isin(prioridades)].copy()
        if q:
            mask = view.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
            view = view[mask]
        view = view if mostrar_valores else sem_valores(view)
        st.dataframe(view, use_container_width=True, hide_index=True)
        _csv, _xlsx = export_frames(view)
        d1, d2 = st.columns(2)
        d1.download_button('Baixar fila em CSV (Excel pt-BR)', _csv, 'fila_fiscalizacao.csv', 'text/csv')
        d2.download_button('Baixar fila em XLSX', _xlsx, 'fila_fiscalizacao.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        st.caption('“Sem registro localizado” não equivale, por si só, a irregularidade. Use a fila para diligência e confirmação.')
        with st.expander('Prova documental: relatório oficial da ANM (Maiores Arrecadadores CFEM)'):
            _reg, _estado = UF_INFO.get(uf, ('', uf))
            _anos = sorted({a.strip() for x in view['anos_cfem'] for a in str(x).split(',') if a.strip()}) if 'anos_cfem' in view else []
            st.markdown(
                f"""Relatório oficial da ANM para anexar ao processo. Para o estado selecionado:
1. Ano: **{', '.join(_anos) if _anos else 'o(s) ano(s) de recolhimento da empresa (coluna `anos_cfem`)'}** — gere um relatório por ano em que a empresa recolheu.
2. Região: **{_reg}** · Estado: **{_estado}**.
3. Arrecadação por: **Empresa** · Ordenado por: **Recolhimento** · clique em **Gerar**.
4. Localize a empresa pela coluna **titular** desta tabela e imprima ou salve em PDF (a página traz o quadro de filtros usado).""")
            st.link_button('Abrir o relatório da ANM', CONFIG['sources']['anm_maiores_arrecadadores'])
            st.caption('Atenção: o relatório identifica a empresa pelo **nome**, sem CNPJ; o vínculo nome–CNPJ vem da coluna titular '
                       '(Cadastro Mineiro) e deve ser conferido. Ele não inclui pagamentos de parcelamento. Anexe também o CSV/XLSX '
                       'desta fila (com CNPJ e anos de recolhimento). Esta ferramenta é triagem; a validade como prova segue o procedimento do Crea.')

elif page == 'Mapa':
    st.header('Mapa da exploração mineral')
    st.caption('Cada ponto é uma área do SIGMINE (ANM) cujo processo aparece na CFEM das empresas filtradas. '
               'O ponto marca o centro da área do processo; não é a localização exata da lavra.')
    _falhou_geo = any(not st.session_state.carga.get(p, (True, ''))[0] for p in ('sigmine', 'municipios'))
    with st.expander('Plano B: enviar arquivos manualmente (SIGMINE e municípios)', expanded=_falhou_geo):
        up_sig = st.file_uploader('SIGMINE (shapefile .zip ou .geojson)', type=['zip', 'geojson', 'json'], key='sigmine_upload')
        if up_sig and st.button('Carregar arquivo SIGMINE'):
            try:
                st.session_state.sigmine = read_sigmine(up_sig.getvalue(), up_sig.name)
                st.success(f'{len(st.session_state.sigmine):,} áreas carregadas do SIGMINE.')
            except Exception as e: st.error(str(e))
        up_kml = st.file_uploader('Limites dos municípios (KML/KMZ)', type=['kml', 'kmz'], key='kml_upload')
        if up_kml and st.button('Carregar KML/KMZ'):
            try:
                st.session_state.municipios = ler_kml(up_kml.getvalue(), up_kml.name)
                st.success(f"{len(st.session_state.municipios['features'])} municípios carregados do KML.")
            except Exception as e: st.error(str(e))
    sig = st.session_state.sigmine
    if base.empty:
        st.warning('Sem dados da CFEM para este estado. Veja o status da carga na barra lateral.')
    elif sig.empty:
        st.info('SIGMINE não carregado. Veja o status na barra lateral ou use o plano B acima.')
    else:
        pontos, stt = pontos_empresas(base, empresas, sig)
        a, b, c = st.columns(3)
        a.metric('Processos da CFEM', f"{stt['processos_cfem']:,}")
        b.metric('Localizados no SIGMINE', f"{stt['localizados']:,}")
        c.metric('Empresas no mapa', f"{pontos['cnpj'].nunique() if len(pontos) else 0:,}")
        if stt['localizados'] == 0:
            st.warning('Nenhum processo da CFEM foi localizado no SIGMINE. Confira o formato do número do processo abaixo.')
            st.write('Exemplos CFEM:', stt['exemplo_cfem'], ' | Exemplos SIGMINE:', stt['exemplo_sigmine'])
            if stt['sem_chave']: st.caption(f"{stt['sem_chave']:,} processos da CFEM sem ano identificável (coluna AnoDoProcesso ou número no formato NNNNNN/AAAA).")
        else:
            disp = [o for o in ['Alta', 'Média', 'Baixa', 'Sem base Crea'] if o in set(pontos['prioridade'].dropna())]
            f1, f2, f3 = st.columns([2, 1, 1])
            sel = f1.multiselect('Prioridade no mapa', disp, default=disp)
            outras = f2.checkbox('Incluir demais áreas do SIGMINE (sem CFEM)', value=False)
            colorir = f3.checkbox('Colorir municípios (empresas Alta)', value=True)
            pts = pontos[pontos['prioridade'].isin(sel)].copy()
            extras = None
            if outras:
                extras = sig[~sig['chave'].isin(stt['chaves_casadas']) & sig['lat'].notna()]
                if len(extras) > 6000:
                    st.caption(f'{len(extras):,} áreas sem CFEM; exibindo as 6.000 primeiras para manter o mapa leve.')
                    extras = extras.head(6000)
            if pts.empty:
                st.info('Nenhum ponto para os filtros escolhidos.')
            else:
                try:
                    mun = copy.deepcopy(st.session_state.municipios) if st.session_state.municipios else None
                    mapa = montar_mapa(pts, mun, stats_municipio(base, empresas), colorir, extras)
                    mostrar_html(mapa.get_root().render(), 680)
                    st.caption('Use o controle no canto superior direito para ligar/desligar camadas. Passe o mouse sobre o ponto '
                               '(titular, CNPJ, anos da CFEM, fase, substância) e sobre o município (empresas e prioridade Alta). '
                               'Mapa base: CARTO/OpenStreetMap (troque no seletor de camadas, inclusive satélite); limites: IBGE.')
                    st.download_button('Baixar mapa em HTML (abre no navegador; precisa de internet para o mapa base)', mapa.get_root().render().encode('utf-8'), 'mapa_mineracao.html', 'text/html')
                except Exception as e: st.error(f'Erro ao montar o mapa: {e}')
                cols_t = [c for c in ['cnpj', 'titular_sigmine', 'prioridade', 'anos_cfem', 'fase', 'substancia_sigmine', 'processo_sigmine', 'lat', 'lon'] if c in pontos]
                _csv, _xlsx = export_frames(pontos[cols_t])
                d1, d2 = st.columns(2)
                d1.download_button('Baixar pontos em CSV', _csv, 'pontos_mapa.csv', 'text/csv')
                d2.download_button('Baixar pontos em XLSX', _xlsx, 'pontos_mapa.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

elif page == 'Legislação e fontes':
    st.header('Base legal e fontes de consulta')
    itens = [
        ('Lei nº 5.194/1966', 'Competência do Sistema Confea/Crea e fiscalização do exercício profissional.', 'https://www.planalto.gov.br/ccivil_03/leis/l5194.htm'),
        ('Lei nº 6.496/1977', 'Institui a ART e define o responsável técnico pelo empreendimento.', CONFIG['sources']['lei_6496']),
        ('Resolução Confea nº 1.008/2004', 'Procedimentos de instauração, instrução e julgamento de processos de infração.', CONFIG['sources']['resolucao_1008']),
        ('Acordo Confea–ANM', 'Cooperação, compartilhamento de dados e combate à informalidade na mineração.', CONFIG['sources']['act_confea_anm']),
        ('Relatório Maiores Arrecadadores CFEM (ANM)', 'Relatório oficial por ano, região, estado e empresa, para impressão como documento de apoio.', CONFIG['sources']['anm_maiores_arrecadadores']),
        ('Dados abertos da ANM', 'Cadastro Mineiro, AMB, CFEM, SIGMINE, SIGBM e demais conjuntos.', CONFIG['sources']['anm_catalogo']),
    ]
    for title, desc, url in itens:
        with st.expander(title):
            st.write(desc); st.markdown(f'[Abrir fonte oficial]({url})')

elif page == 'Checklist remoto':
    st.header('Checklist de fiscalização remota')
    st.caption('Roteiro de triagem. A capitulação e os atos processuais devem ser definidos pelo Crea competente.')
    sections = {
      'Identificação': ['CNPJ e razão social conferidos', 'Município e endereço do empreendimento conferidos', 'Processo(s) ANM e situação atual registrados', 'Substância e regime de aproveitamento identificados'],
      'Indícios de operação': ['Produção/RAL localizado', 'CFEM localizada', 'Título ou fase compatível com operação', 'SIGMINE ou SIGBM consultado quando aplicável'],
      'Exercício profissional': ['Registro ou visto da empresa consultado', 'Responsável técnico consultado', 'ARTs relacionadas consultadas', 'Serviços de geologia, minas, estruturas, segurança ou manutenção identificados'],
      'Encaminhamento': ['Evidências públicas arquivadas com data e fonte', 'Notificação revisada por agente fiscal', 'Prazo e canal de resposta definidos', 'Caso priorizado para visita quando necessário'],
    }
    done = 0
    for sec, items in sections.items():
        st.subheader(sec)
        for item in items:
            if st.checkbox(item, key=sec+item): done += 1
    st.progress(done / sum(map(len, sections.values())))
    st.write(f'{done} de {sum(map(len, sections.values()))} itens concluídos.')

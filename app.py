from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from anm_client import download_dataset
from data_utils import CONFIG, read_uploaded, normalize, enrich, company_summary, export_frames

st.set_page_config(page_title=CONFIG['app']['title'], page_icon='⛏️', layout='wide')

if 'minerios' not in st.session_state: st.session_state.minerios = pd.DataFrame()
if 'crea' not in st.session_state: st.session_state.crea = pd.DataFrame()

with st.sidebar:
    st.title('Fiscalização Minerária')
    st.caption('Sistema Confea/Crea • ANM')
    page = st.radio('Navegação', ['Painel', 'Empresas', 'Importação de dados', 'Legislação e fontes', 'Checklist remoto'])
    st.divider()
    if st.button('Atualizar dados públicos da ANM', use_container_width=True):
        with st.spinner('Baixando CFEM e Cadastro Mineiro...'):
            frames, sources, errors = [], [], []
            direct = st.session_state.get('anm_direct_urls', {})
            for dataset in ('cfem', 'cadastro_mineiro'):
                try:
                    df, meta = download_dataset(dataset, direct.get(dataset) or None)
                    frames.append(df); sources.append(meta)
                except Exception as exc: errors.append(f'{dataset}: {exc}')
            if frames:
                raw_all = pd.concat(frames, ignore_index=True, sort=False)
                st.session_state.minerios = normalize(raw_all)
                if st.session_state.minerios.empty:
                    st.error('Os arquivos foram baixados, mas nenhuma linha tem CNPJ válido (14 dígitos). '
                             'Confira abaixo as colunas recebidas e ajuste os nomes em config.yaml (seção columns).')
                    for (ds, f) in zip(('cfem', 'cadastro_mineiro'), frames):
                        st.caption(f'{ds}: {len(f):,} linhas • colunas: ' + ', '.join(map(str, f.columns)))
                        st.dataframe(f.head(3), use_container_width=True)
                st.session_state.anm_sources = sources
                st.session_state.anm_updated = pd.Timestamp.now(tz='UTC').isoformat()
                st.success(f'{len(st.session_state.minerios):,} linhas empresariais carregadas.')
                if any(s.get('insecure_tls_fallback') for s in sources):
                    st.warning('A ANM foi acessada por fallback TLS restrito ao domínio público dadosabertos.anm.gov.br. Verifique a atualização do certificado do servidor ANM antes de uso institucional.')
            if errors: st.warning(' | '.join(errors))
    if st.session_state.get('anm_updated'):
        st.caption('Última atualização: ' + st.session_state.anm_updated)
    st.caption('A base pública é um apoio à triagem. A confirmação de infração exige análise do agente fiscal.')
    st.divider()
    _ufs = sorted({u for u in st.session_state.minerios.get('uf', pd.Series(dtype=str)).dropna().tolist() if u})
    _padrao = [CONFIG['app'].get('default_uf')] if CONFIG['app'].get('default_uf') in _ufs else []
    ufs = st.multiselect('UF', _ufs, default=_padrao, placeholder='Todas as UFs')

base = enrich(st.session_state.minerios, st.session_state.crea)
if ufs and not base.empty: base = base[base.uf.isin(ufs)]
with st.sidebar:
    municipios = ['Todos'] + sorted(base.municipio[base.municipio.ne('')].dropna().unique().tolist()) if not base.empty else ['Todos']
    municipio = st.selectbox('Município', municipios)
if municipio != 'Todos' and not base.empty: base = base[base.municipio.eq(municipio)]
empresas = company_summary(base)

if page == 'Importação de dados':
    st.header('Importação e atualização de dados')
    st.info('Use “Atualizar dados públicos da ANM” na barra lateral para buscar CFEM e Cadastro Mineiro. O upload manual permanece como contingência.')
    st.subheader('Links diretos opcionais dos arquivos')
    st.caption('O catálogo dados.gov.br é dinâmico. Se a página não expuser automaticamente os CSVs, cole aqui os links diretos dos recursos, um por linha.')
    c0, c1 = st.columns(2)
    with c0:
        cfem_urls = st.text_area('Recursos CFEM', value='\n'.join(st.session_state.get('anm_direct_urls', {}).get('cfem', [])), height=100)
    with c1:
        cm_urls = st.text_area('Recursos Cadastro Mineiro', value='\n'.join(st.session_state.get('anm_direct_urls', {}).get('cadastro_mineiro', [])), height=100)
    if st.button('Salvar links diretos'):
        st.session_state.anm_direct_urls = {'cfem': [x.strip() for x in cfem_urls.splitlines() if x.strip()], 'cadastro_mineiro': [x.strip() for x in cm_urls.splitlines() if x.strip()]}
        st.success('Links salvos nesta sessão. Use o botão de atualização na barra lateral.')
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
        st.dataframe(empresas.sort_values(['prioridade','qtd_processos'], ascending=[True,False]), use_container_width=True, hide_index=True)

elif page == 'Empresas':
    st.header('Empresas e empreendimentos')
    if empresas.empty: st.info('Carregue uma base para consultar empresas.')
    else:
        q = st.text_input('Pesquisar por CNPJ, razão social, município ou substância')
        prioridades = st.multiselect('Prioridade', sorted(empresas.prioridade.dropna().unique()), default=sorted(empresas.prioridade.dropna().unique()))
        view = empresas[empresas.prioridade.isin(prioridades)].copy()
        if q:
            mask = view.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
            view = view[mask]
        st.dataframe(view, use_container_width=True, hide_index=True)
        _csv, _xlsx = export_frames(view)
        d1, d2 = st.columns(2)
        d1.download_button('Baixar fila em CSV (Excel pt-BR)', _csv, 'fila_fiscalizacao.csv', 'text/csv')
        d2.download_button('Baixar fila em XLSX', _xlsx, 'fila_fiscalizacao.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        st.caption('“Sem registro localizado” não equivale, por si só, a irregularidade. Use a fila para diligência e confirmação.')

elif page == 'Legislação e fontes':
    st.header('Base legal e fontes de consulta')
    itens = [
        ('Lei nº 5.194/1966', 'Competência do Sistema Confea/Crea e fiscalização do exercício profissional.', 'https://www.planalto.gov.br/ccivil_03/leis/l5194.htm'),
        ('Lei nº 6.496/1977', 'Institui a ART e define o responsável técnico pelo empreendimento.', CONFIG['sources']['lei_6496']),
        ('Resolução Confea nº 1.008/2004', 'Procedimentos de instauração, instrução e julgamento de processos de infração.', CONFIG['sources']['resolucao_1008']),
        ('Acordo Confea–ANM', 'Cooperação, compartilhamento de dados e combate à informalidade na mineração.', CONFIG['sources']['act_confea_anm']),
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

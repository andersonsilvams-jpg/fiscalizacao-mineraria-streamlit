from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from data_utils import CONFIG, read_uploaded, normalize, enrich, company_summary

st.set_page_config(page_title=CONFIG['app']['title'], page_icon='⛏️', layout='wide')

if 'minerios' not in st.session_state: st.session_state.minerios = pd.DataFrame()
if 'crea' not in st.session_state: st.session_state.crea = pd.DataFrame()

with st.sidebar:
    st.title('Fiscalização Minerária')
    st.caption('Sistema Confea/Crea • ANM')
    page = st.radio('Navegação', ['Painel', 'Empresas', 'Importação de dados', 'Legislação e fontes', 'Checklist remoto'])
    st.divider()
    uf = st.selectbox('Regional responsável', ['Todos'] + sorted(set(st.session_state.minerios.get('uf', pd.Series(dtype=str)).dropna().tolist())))
    st.caption('A base pública é um apoio à triagem. A confirmação de infração exige análise do agente fiscal.')

base = enrich(st.session_state.minerios, st.session_state.crea)
if uf != 'Todos' and not base.empty: base = base[base.uf.eq(uf)]
empresas = company_summary(base)

if page == 'Importação de dados':
    st.header('Importação e atualização de dados')
    st.info('As bases da ANM são públicas, mas os formatos e endereços de arquivos podem mudar. O MVP aceita os arquivos baixados da ANM e dados internos autorizados do Crea.')
    c1, c2 = st.columns(2)
    with c1:
        st.subheader('ANM — mineração')
        up = st.file_uploader('CSV, XLSX ou Parquet', type=['csv','xlsx','xls','parquet'], key='anm')
        if up and st.button('Carregar base ANM'):
            try:
                st.session_state.minerios = normalize(read_uploaded(up))
                st.success(f'{len(st.session_state.minerios):,} registros empresariais carregados.')
            except Exception as e: st.error(str(e))
    with c2:
        st.subheader('Crea — registros/ARTs')
        upc = st.file_uploader('Arquivo autorizado do Crea', type=['csv','xlsx','xls','parquet'], key='crea')
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
        st.download_button('Baixar fila em CSV', view.to_csv(index=False).encode('utf-8-sig'), 'fila_fiscalizacao.csv', 'text/csv')
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

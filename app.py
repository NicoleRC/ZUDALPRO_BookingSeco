from datetime import datetime, time
import io
import os
import sqlite3
import pandas as pd
import streamlit as st

# =========================================================
# 0. CONFIGURACIÓN DE PÁGINA (DEBE SER LO PRIMERO)
# =========================================================
st.set_page_config(
    page_title="Booking ZUDALPRO - Almacén Seco", page_icon="📅", layout="wide"
)

# 1. Diccionario con los usuarios permitidos y sus respectivas contraseñas
USUARIOS_CONTRASENAS = {
    "lsuarez": "ls30",
    "kmoreno": "km23",
    "nramirez": "nr29",
    "durribarri": "du30",
    "fgonzalez": "fg10",
    "krodriguez": "kr05",
    "cberroteran": "cb31",
    "icarrillo": "c",
}

st.sidebar.title("🔐 Control de Acceso")

# 2. Inicializar el estado de autenticación si no existe
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario_actual"] = ""

# 3. Si aún no ha iniciado sesión, mostrar los campos en la barra lateral
if not st.session_state["autenticado"]:
    usuario_seleccionado = st.sidebar.selectbox(
        "Seleccione su usuario:", 
        options=list(USUARIOS_CONTRASENAS.keys())
    )
    password_ingresada = st.sidebar.text_input("Contraseña:", type="password")

    if st.sidebar.button("Iniciar Sesión"):
        if password_ingresada == USUARIOS_CONTRASENAS.get(usuario_seleccionado):
            st.session_state["autenticado"] = True
            st.session_state["usuario_actual"] = usuario_seleccionado
            st.sidebar.success(f"¡Acceso concedido, {usuario_seleccionado}!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta.")

    st.warning("⚠️ Por favor, seleccione su usuario e ingrese su contraseña en la barra lateral para ver la aplicación.")
    st.stop()


# ---------------------------------------------------------
# 1. INICIALIZAR, MIGRAR Y LIMPIAR DUPLICADOS EN LA DB
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect("bookings.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_registro TEXT,
            semana TEXT,
            dia_asignado TEXT,
            familia TEXT,
            proveedor TEXT,
            producto TEXT,
            odc TEXT,
            observacion_compras TEXT,
            recepcion_almacen INTEGER DEFAULT 0,
            observacion_almacen TEXT,
            usuario_windows TEXT,
            fuera_de_tiempo INTEGER DEFAULT 0,
            eliminado INTEGER DEFAULT 0
        )
    """)

    columnas_nuevas = [
        ("familia", "TEXT"),
        ("producto", "TEXT"),
        ("observacion_compras", "TEXT"),
        ("recepcion_almacen", "INTEGER DEFAULT 0"),
        ("observacion_almacen", "TEXT"),
        ("fuera_de_tiempo", "INTEGER DEFAULT 0"),
        ("eliminado", "INTEGER DEFAULT 0"),
    ]
    for col, def_val in columnas_nuevas:
        try:
            cursor.execute(f"ALTER TABLE historico_bookings ADD COLUMN {col} {def_val}")
        except sqlite3.OperationalError:
            pass

    # Limpieza automática de duplicados por seguridad
    cursor.execute("""
        DELETE FROM historico_bookings 
        WHERE id NOT IN (
            SELECT MAX(id) 
            FROM historico_bookings 
            GROUP BY odc, semana, dia_asignado
        )
    """)

    conn.commit()
    conn.close()


init_db()

# Título principal de la app
st.title("📅 Planificación de Compras Almacén Seco - ZUDALPRO")

# Obtener usuario actual desde la sesión activa
usuario_actual = st.session_state["usuario_actual"]

# Permisos de almacén: lsuarez y kmoreno gestionan recepción y movimientos por llegada distinta
USUARIOS_AUTORIZADOS_ALMACEN = ["lsuarez", "kmoreno"]
es_autorizado = usuario_actual in USUARIOS_AUTORIZADOS_ALMACEN

# Menú lateral
menu = st.sidebar.selectbox("Menú de Navegación", ["Booking", "Histórico"])

# Opciones predefinidas
FAMILIAS_DISPONIBLES = ["PROCURA", "VIVERES", "LIMPIEZA", "EMPAQUES"]
DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]


# Función para cargar proveedores desde el archivo .txt
def cargar_proveedores():
    if os.path.exists("proveedores.txt"):
        with open("proveedores.txt", "r", encoding="utf-8") as f:
            proveedores = [line.strip() for line in f if line.strip()]
        return proveedores
    else:
        return []


PROVEEDORES_DISPONIBLES = cargar_proveedores()

# Calcular semana actual (Ej: 2026-SEM 45)
ahora = datetime.now()
ano, semana_num, _ = ahora.isocalendar()
semana_actual_str = f"{ano}-SEM {semana_num:02d}"
dias_map = {"Lunes": 0, "Martes": 1, "Miércoles": 2, "Jueves": 3, "Viernes": 4}

# ---------------------------------------------------------
# 2. VISTA: CALENDARIO VISUAL + FORMULARIO + EXCEL PROFESIONAL
# ---------------------------------------------------------
if menu == "Booking":
    st.subheader(
        f"📅 Calendario Semanal de Operaciones ({semana_actual_str})"
    )

    if not es_autorizado:
        st.info(
            f"👤 Usuario conectado: `{usuario_actual}` (Modo registro y consulta)"
        )
    else:
        st.success(
            f"🔐 Usuario autorizado con privilegios de almacén:"
            f" `{usuario_actual}`"
        )

    # Consultar registros activos de la semana actual
    conn = sqlite3.connect("bookings.db")
    df_semana_actual = pd.read_sql_query(
        "SELECT * FROM historico_bookings WHERE semana = ? AND (eliminado = 0 OR eliminado IS NULL)",
        conn,
        params=(semana_actual_str,),
    )
    
    # Consultar registros eliminados de la semana actual para mostrar la alerta
    df_eliminados_semana = pd.read_sql_query(
        "SELECT * FROM historico_bookings WHERE semana = ? AND eliminado = 1",
        conn,
        params=(semana_actual_str,),
    )
    conn.close()

    cols = st.columns(5)

    for i, dia in enumerate(DIAS_SEMANA):
        with cols[i]:
            st.markdown(f"### **{dia}**")
            df_dia = df_semana_actual[df_semana_actual["dia_asignado"] == dia]
            df_dia_eliminados = df_eliminados_semana[df_eliminados_semana["dia_asignado"] == dia]

            if not df_dia.empty:
                df_excel_dia = df_dia[[
                    "familia",
                    "proveedor",
                    "producto",
                    "odc",
                    "observacion_compras",
                    "recepcion_almacen",
                    "observacion_almacen",
                ]].copy()
                df_excel_dia.columns = [
                    "FAMILIA",
                    "PROVEEDOR",
                    "PRODUCTO",
                    "OC",
                    "OBSERVACIONES - COMPRAS",
                    "RECEPCION ALMACEN",
                    "OBSERVACIONES - ALMACEN",
                ]
                df_excel_dia["RECEPCION ALMACEN"] = df_excel_dia[
                    "RECEPCION ALMACEN"
                ].apply(lambda x: "SI" if x == 1 else "NO")

                output = io.BytesIO()
                with pd.ExcelWriter(output) as writer:
                    df_excel_dia.to_excel(
                        writer, index=False, sheet_name=f"Planificacion_{dia}"
                    )
                excel_bytes = output.getvalue()

                st.download_button(
                    label=f"📥 Excel {dia}",
                    data=excel_bytes,
                    file_name=f"Planificacion_{semana_actual_str}_{dia}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_excel_{dia}",
                )
            st.divider()

            # 1. Mostrar Alerta de Proveedores Eliminados en este día
            for _, row_el in df_dia_eliminados.iterrows():
                with st.container(border=True):
                    st.error(
                        f"❌ **PROVEEDOR ELIMINADO**\n\n**{row_el['proveedor']}**\n*Prod:* {row_el['producto']}\n*OC:* `{row_el['odc']}`"
                    )

            if not df_dia.empty:
                df_a_tiempo = df_dia[df_dia["fuera_de_tiempo"] == 0]
                df_tarde = df_dia[df_dia["fuera_de_tiempo"] == 1]

                # Función común para renderizar las tarjetas con soporte de alertas visuales
                def renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=False):
                    rec_val = bool(row["recepcion_almacen"])
                    obs_alm = row["observacion_almacen"] or ""
                    obs_compras_actual = (
                        str(row["observacion_compras"])
                        if pd.notna(row["observacion_compras"])
                        else ""
                    )

                    # Verificar si fue movido por almacén buscando la etiqueta en las observaciones
                    fue_movido_almacen = "[MOVIDO POR ALMACÉN]" in obs_compras_actual

                    es_creador = str(row["usuario_windows"]).lower() == usuario_actual.lower()
                    puede_editar_almacen = es_autorizado or es_creador

                    with st.container(border=True):
                        # Alerta visual en rojo si es fuera de tiempo o si fue movido por almacén con día distinto
                        if es_fuera_de_tiempo_grupo:
                            st.error(
                                f"🚨 **FUERA DE TIEMPO**\n\n**{row['proveedor']}**\n*Prod:* {row['producto']}\n*OC:* `{row['odc']}`"
                            )
                        elif fue_movido_almacen:
                            st.error(
                                f"⚠️ **PROVEEDOR LLEGÓ DÍA DISTINTO**\n\n**{row['proveedor']}**\n*Prod:* {row['producto']}\n*OC:* `{row['odc']}`"
                            )
                        else:
                            st.markdown(
                                f"**{row['proveedor']}**\n\n*Prod:* {row['producto']}\n*OC:* `{row['odc']}`"
                                f" | *Fam:* {row['familia']}"
                            )
                        
                        if obs_compras_actual:
                            st.text(f"Obs Compras: {obs_compras_actual}")

                        label_rec = "Recibido Almacén (Tarde)" if es_fuera_de_tiempo_grupo else "Recibido Almacén"
                        key_suf = "t_" if es_fuera_de_tiempo_grupo else ""

                        nuevo_rec = st.checkbox(
                            label_rec,
                            value=rec_val,
                            key=f"rec_{key_suf}{row['id']}",
                            disabled=not puede_editar_almacen,
                        )
                        nueva_obs_alm = st.text_input(
                            "Obs. Almacén",
                            value=obs_alm,
                            key=f"obs_alm_{key_suf}{row['id']}",
                            disabled=not puede_editar_almacen,
                        )

                        if puede_editar_almacen and (
                            nuevo_rec != rec_val or nueva_obs_alm != obs_alm
                        ):
                            conn = sqlite3.connect("bookings.db")
                            cursor = conn.cursor()
                            cursor.execute(
                                """UPDATE historico_bookings SET recepcion_almacen = ?, observacion_almacen = ? WHERE id = ?""",
                                (1 if nuevo_rec else 0, nueva_obs_alm, row["id"]),
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()

                        # Opción para mover de día (Permitida al Creador O al personal de Almacén)
                        with st.expander("⚙️ Mover de día"):
                            if not (es_creador or es_autorizado):
                                st.warning(
                                    f"🔒 Solo el creador (`{row['usuario_windows']}`) o Almacén pueden moverlo de día."
                                )
                            else:
                                nuevo_dia = st.selectbox(
                                    "Cambiar al día:",
                                    DIAS_SEMANA,
                                    index=DIAS_SEMANA.index(row["dia_asignado"]),
                                    key=f"cambiar_dia_{key_suf}{row['id']}",
                                )
                                if nuevo_dia != row["dia_asignado"]:
                                    dia_origen = row["dia_asignado"]
                                    conn = sqlite3.connect("bookings.db")
                                    cursor = conn.cursor()

                                    # Generar traza clara indicando origen y destino
                                    if es_autorizado and not es_creador:
                                        aviso_nuevo = f"🔄 [MOVIDO POR ALMACÉN: {usuario_actual}] Reprogramado desde {dia_origen} hacia {nuevo_dia}"
                                    else:
                                        aviso_nuevo = f"🔄 Reprogramado desde {dia_origen} hacia {nuevo_dia} por {usuario_actual}"

                                    if obs_compras_actual:
                                        nueva_nota_final = f"{obs_compras_actual} | {aviso_nuevo}"
                                    else:
                                        nueva_nota_final = aviso_nuevo

                                    cursor.execute(
                                        """UPDATE historico_bookings SET dia_asignado = ?, observacion_compras = ? WHERE id = ?""",
                                        (nuevo_dia, nueva_nota_final, row["id"]),
                                    )
                                    conn.commit()
                                    conn.close()
                                    st.success(f"¡Movido de {dia_origen} a {nuevo_dia} con éxito!")
                                    st.rerun()

                        # Opción para eliminar del Booking (Solo si es creador Y NO HA SIDO RECIBIDO)
                        with st.expander("🗑️ Eliminar del Booking"):
                            if not es_creador:
                                st.warning(
                                    f"🔒 Solo el usuario que registró este booking (`{row['usuario_windows']}`) puede eliminarlo."
                                )
                            elif rec_val:
                                st.error("❌ Este booking ya fue recibido en almacén; no se puede eliminar.")
                            else:
                                st.warning("⚠️ Esto ocultará el proveedor del calendario semanal, pero quedará registrado en el histórico.")
                                if st.button("Confirmar Eliminación", key=f"btn_eliminar_{key_suf}{row['id']}"):
                                    conn = sqlite3.connect("bookings.db")
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        """UPDATE historico_bookings SET eliminado = 1 WHERE id = ?""",
                                        (row["id"],)
                                    )
                                    conn.commit()
                                    conn.close()
                                    st.success("¡El proveedor ha sido marcado como eliminado del booking!")
                                    st.rerun()

                        st.caption(
                            f"🕒 Reg: {row['fecha_registro']} | 👤 {row['usuario_windows']}"
                        )

                # Procesar registros a tiempo
                for _, row in df_a_tiempo.iterrows():
                    renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=False)

                # Procesar registros fuera de tiempo
                for _, row in df_tarde.iterrows():
                    renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=True)

            elif df_dia.empty and df_dia_eliminados.empty:
                st.info("Sin booking asignado")

    st.divider()

    # Formulario de Registro
    st.subheader("📝 Registrar Nueva Orden de Compra (Booking)")

    col1, col2, col3 = st.columns(3)

    with col1:
        dia_asignado = st.selectbox(
            "Despacho Estimado (Día)", DIAS_SEMANA, key="form_dia"
        )
        familia = st.selectbox("Familia", FAMILIAS_DISPONIBLES, key="form_familia")

        modo_proveedor = st.radio(
            "Tipo de Proveedor",
            ["Seleccionar de la lista", "Escribir nuevo proveedor"],
            horizontal=True,
            key="form_modo_prov",
        )

        if modo_proveedor == "Seleccionar de la lista":
            proveedor = st.selectbox(
                "Proveedor", [""] + PROVEEDORES_DISPONIBLES, key="form_prov_select"
            )
        else:
            proveedor = st.text_input(
                "Nombre del Proveedor (Manual)", key="form_prov_texto_libre"
            )

    with col2:
        producto = st.text_input("Producto", key="form_prod")
        odc = st.text_input("Número de OC (Orden de Compra)", key="form_odc")

    with col3:
        observacion_compras = st.text_area("Observaciones - Compras", key="form_obs")

    enviar = st.button("Guardar y Registrar Booking", key="btn_guardar_booking")

    if enviar:
        if not odc or not producto or not proveedor:
            st.warning("⚠️ Por favor completa el Producto, la OC y el Proveedor.")
        else:
            fecha_registro_str = ahora.strftime("%Y-%m-%d %H:%M:%S")

            dia_asignado_idx = dias_map.get(dia_asignado)
            dia_actual_idx = ahora.weekday()
            hora_actual = ahora.time()

            es_mismo_dia = dia_asignado_idx == dia_actual_idx
            es_despues_de_8am = hora_actual > time(8, 0)
            fuera_de_tiempo = 1 if (es_mismo_dia and es_despues_de_8am) else 0

            conn = sqlite3.connect("bookings.db")
            cursor = conn.cursor()
            cursor.execute(
                """
                    INSERT INTO historico_bookings 
                    (fecha_registro, semana, dia_asignado, familia, proveedor, producto, odc, observacion_compras, usuario_windows, fuera_de_tiempo, eliminado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    fecha_registro_str,
                    semana_actual_str,
                    dia_asignado,
                    familia,
                    proveedor,
                    producto,
                    odc,
                    observacion_compras,
                    usuario_actual,
                    fuera_de_tiempo,
                ),
            )
            conn.commit()
            conn.close()

            if fuera_de_tiempo:
                st.warning(
                    "⚠️ Guardado con éxito, pero marcado como **FUERA DE TIEMPO**"
                    " (registrado después de las 8:00 AM del mismo día)."
                )
            else:
                st.success("✅ ¡Booking registrado con éxito!")
            st.rerun()

# ---------------------------------------------------------
# 3. VISTA: HISTÓRICO GENERAL Y REPORTES
# ---------------------------------------------------------
else:
    st.subheader("📊 Histórico General por Semana")

    conn = sqlite3.connect("bookings.db")
    df_todos = pd.read_sql_query(
        "SELECT * FROM historico_bookings ORDER BY fecha_registro DESC", conn
    )
    conn.close()

    if not df_todos.empty:
        semanas_disponibles = ["📅 Todas las semanas"] + df_todos["semana"].unique().tolist()
        semana_seleccionada = st.selectbox(
            "Selecciona la Semana a Consultar", semanas_disponibles
        )

        if semana_seleccionada == "📅 Todas las semanas":
            df_filtrado = df_todos
            nombre_archivo = "Reporte_General_Todas_Las_Semanas.xlsx"
            nombre_hoja = "Historico_General"
            label_boton = "📥 Descargar Reporte Completo de *Todas las Semanas* (Excel)"
        else:
            df_filtrado = df_todos[df_todos["semana"] == semana_seleccionada]
            nombre_archivo = f"Reporte_General_{semana_seleccionada}.xlsx"
            nombre_hoja = "Historico_Semanal"
            label_boton = f"📥 Descargar Reporte Completo de la {semana_seleccionada} (Excel)"

        st.dataframe(df_filtrado, use_container_width=True)

        df_excel_gen = df_filtrado[[
            "semana",
            "dia_asignado",
            "familia",
            "proveedor",
            "producto",
            "odc",
            "observacion_compras",
            "recepcion_almacen",
            "observacion_almacen",
            "eliminado",
        ]].copy()
        
        df_excel_gen.columns = [
            "SEMANA",
            "DIA",
            "FAMILIA",
            "PROVEEDOR",
            "PRODUCTO",
            "OC",
            "OBSERVACIONES - COMPRAS",
            "RECEPCION ALMACEN",
            "OBSERVACIONES - ALMACEN",
            "ELIMINADO",
        ]
        
        df_excel_gen["RECEPCION ALMACEN"] = df_excel_gen["RECEPCION ALMACEN"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )
        df_excel_gen["ELIMINADO"] = df_excel_gen["ELIMINADO"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )

        output = io.BytesIO()
        with pd.ExcelWriter(output) as writer:
            df_excel_gen.to_excel(writer, index=False, sheet_name=nombre_hoja)
        excel_data = output.getvalue()

        st.download_button(
            label=label_boton,
            data=excel_data,
            file_name=nombre_archivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("Aún no hay registros guardados en la base de datos.")

st.sidebar.success(f"Sesión activa: **{st.session_state['usuario_actual']}**")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state["autenticado"] = False
    st.session_state["usuario_actual"] = ""
    st.rerun()
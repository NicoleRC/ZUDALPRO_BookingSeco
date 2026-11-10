from datetime import datetime, time, timedelta
from streamlit_autorefresh import st_autorefresh
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

# Refresco automático cada 5 segundos para sincronizar en tiempo real
count = st_autorefresh(interval=5000, limit=None, key="frecuencia_refresco")

# 1. Diccionario con los usuarios permitidos y sus respectivas contraseñas
USUARIOS_CONTRASENAS = {
    "lsuarez": "ls30",
    "kmoreno": "km23",
    "nramirez": "nr29",
    "durribarri": "du30",
    "fgonzalez": "fg10",
    "krodriguez": "r05",
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
            eliminado INTEGER DEFAULT 0,
            ultima_modificacion TEXT
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
        ("ultima_modificacion", "TEXT"),
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

# Permisos de almacén: lsuarez y kmoreno gestionan recepción y movimientos
USUARIOS_AUTORIZADOS_ALMACEN = ["lsuarez", "kmoreno"]
es_autorizado = usuario_actual in USUARIOS_AUTORIZADOS_ALMACEN

# Menú lateral
menu = st.sidebar.selectbox("Menú de Navegación", ["Booking", "Histórico"])

# Opciones predefinidas
FAMILIAS_DISPONIBLES = ["PROCURA", "VIVERES", "LIMPIEZA", "EMPAQUES"]
DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
dias_map = {"Lunes": 0, "Martes": 1, "Miércoles": 2, "Jueves": 3, "Viernes": 4}


# Función para cargar proveedores desde el archivo .txt
def cargar_proveedores():
    if os.path.exists("proveedores.txt"):
        with open("proveedores.txt", "r", encoding="utf-8") as f:
            proveedores = [line.strip() for line in f if line.strip()]
        return proveedores
    else:
        return []


PROVEEDORES_DISPONIBLES = cargar_proveedores()

# Función para obtener la hora local ajustada a Venezuela (UTC-4) desde el servidor en la nube
def obtener_ahora_local():
    return datetime.utcnow() - timedelta(hours=4)

# Calcular fecha y hora actual local
ahora = obtener_ahora_local()
ano, semana_num, _ = ahora.isocalendar()
semana_actual_str = f"{ano}-SEM {semana_num:02d}"

dia_actual_idx = ahora.weekday() # 0: Lunes, ..., 4: Viernes, 5/6: Sábado/Domingo
hora_actual = ahora.time()

# Filtrar días permitidos para evitar mover o registrar en días pasados
if dia_actual_idx > 4:
    dias_permitidos_edicion = []
else:
    dias_permitidos_edicion = [d for d in DIAS_SEMANA if dias_map[d] >= dia_actual_idx]

# ---------------------------------------------------------
# 2. VISTA: CALENDARIO VISUAL + FORMULARIO + EXCEL PROFESIONAL
# ---------------------------------------------------------
if menu == "Booking":
    st.subheader(
        f"📅 Calendario Semanal de Operaciones ({semana_actual_str})"
    )

    if not es_autorizado:
        st.info(
            f"🛒 Usuario conectado: `{usuario_actual}` (Perfil: **Compras** - Registro y gestión de bookings)"
        )
    else:
        st.success(
            f"🔐 Usuario autorizado con privilegios de almacén:"
            f" `{usuario_actual}` (Perfil: **Almacén**)"
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

    # --- BOTÓN MAESTRO DE DESCARGA DE TODA LA SEMANA (LUNES A VIERNES) ---
    if not df_semana_actual.empty:
        df_excel_semana_completa = df_semana_actual[[
            "dia_asignado",
            "familia",
            "proveedor",
            "producto",
            "odc",
            "observacion_compras",
            "recepcion_almacen",
            "observacion_almacen",
            "ultima_modificacion",
        ]].copy()
        
        df_excel_semana_completa.columns = [
            "DIA",
            "FAMILIA",
            "PROVEEDOR",
            "PRODUCTO",
            "OC",
            "OBSERVACIONES - COMPRAS",
            "RECEPCION ALMACEN",
            "OBSERVACIONES - ALMACEN",
            "ULTIMA MODIFICACION",
        ]
        
        df_excel_semana_completa["RECEPCION ALMACEN"] = df_excel_semana_completa["RECEPCION ALMACEN"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )

        output_sem = io.BytesIO()
        with pd.ExcelWriter(output_sem) as writer:
            df_excel_semana_completa.to_excel(writer, index=False, sheet_name=f"Semana_{semana_actual_str}")
        excel_bytes_sem = output_sem.getvalue()

        st.download_button(
            label=f"📥 Descargar Calendario Completo de la Semana ({semana_actual_str}) - Lunes a Viernes (Excel)",
            data=excel_bytes_sem,
            file_name=f"Calendario_Completo_{semana_actual_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_descargar_semana_completa",
        )
        st.divider()

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
                    "ultima_modificacion",
                ]].copy()
                df_excel_dia.columns = [
                    "FAMILIA",
                    "PROVEEDOR",
                    "PRODUCTO",
                    "OC",
                    "OBSERVACIONES - COMPRAS",
                    "RECEPCION ALMACEN",
                    "OBSERVACIONES - ALMACEN",
                    "ULTIMA MODIFICACION",
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

                def renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=False):
                    rec_val = bool(row["recepcion_almacen"])
                    obs_alm = row["observacion_almacen"] or ""
                    obs_compras_actual = (
                        str(row["observacion_compras"])
                        if pd.notna(row["observacion_compras"])
                        else ""
                    )

                    fue_movido_almacen = "[MOVIDO POR ALMACÉN]" in obs_compras_actual
                    es_creador = str(row["usuario_windows"]).lower() == usuario_actual.lower()
                    puede_editar_almacen = es_autorizado or es_creador

                    dia_booking_idx = dias_map.get(row["dia_asignado"], 0)
                    es_dia_pasado = dia_actual_idx > 4 or dia_booking_idx < dia_actual_idx
                    es_mismo_dia_despues_8am = (dia_booking_idx == dia_actual_idx) and (hora_actual > time(8, 0))

                    bloquear_por_tiempo_compras = (not es_autorizado) and (es_dia_pasado or es_mismo_dia_despues_8am)

                    with st.container(border=True):
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

                        bloquear_recepcion_por_dia = es_dia_pasado and not es_autorizado

                        nuevo_rec = st.checkbox(
                            label_rec,
                            value=rec_val,
                            key=f"rec_{key_suf}{row['id']}",
                            disabled=not puede_editar_almacen or bloquear_recepcion_por_dia,
                        )
                        nueva_obs_alm = st.text_input(
                            "Obs. Almacén",
                            value=obs_alm,
                            key=f"obs_alm_{key_suf}{row['id']}",
                            disabled=not puede_editar_almacen or bloquear_recepcion_por_dia,
                        )

                        if bloquear_por_tiempo_compras:
                            st.caption("🔒 *Pasadas las 8:00 AM del día de recepción; Compras ya no puede modificar este booking.*")

                        if puede_editar_almacen and not bloquear_recepcion_por_dia and (
                            nuevo_rec != rec_val or nueva_obs_alm != obs_alm
                        ):
                            tiempo_actual_str = obtener_ahora_local().strftime("%Y-%m-%d %H:%M:%S")
                            conn = sqlite3.connect("bookings.db")
                            cursor = conn.cursor()
                            cursor.execute(
                                """UPDATE historico_bookings SET recepcion_almacen = ?, observacion_almacen = ?, ultima_modificacion = ? WHERE id = ?""",
                                (1 if nuevo_rec else 0, nueva_obs_alm, tiempo_actual_str, row["id"]),
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()

                        # Opción para editar detalles principales
                        with st.expander("✏️ Editar Datos del Booking"):
                            if bloquear_por_tiempo_compras:
                                st.warning("🔒 No puedes editar los datos de este booking porque ya pasaron las 8:00 AM del día de recepción.")
                            elif not es_creador:
                                st.warning(f"🔒 Solo el creador de este booking (`{row['usuario_windows']}`) puede editar sus datos.")
                            else:
                                nuevo_prov_val = st.text_input("Proveedor", value=row["proveedor"], key=f"edit_prov_{key_suf}{row['id']}")
                                nuevo_prod_val = st.text_input("Producto", value=row["producto"], key=f"edit_prod_{key_suf}{row['id']}")
                                nueva_odc_val = st.text_input("Número de OC", value=str(row["odc"]), key=f"edit_odc_{key_suf}{row['id']}")
                                
                                fam_actual = row["familia"] if row["familia"] in FAMILIAS_DISPONIBLES else FAMILIAS_DISPONIBLES[0]
                                nueva_fam_val = st.selectbox("Familia", FAMILIAS_DISPONIBLES, index=FAMILIAS_DISPONIBLES.index(fam_actual), key=f"edit_fam_{key_suf}{row['id']}")
                                
                                nueva_obs_compras_val = st.text_area("Observaciones - Compras", value=obs_compras_actual, key=f"edit_obs_c_{key_suf}{row['id']}")

                                if st.button("Guardar Cambios", key=f"btn_guardar_edit_{key_suf}{row['id']}"):
                                    if not nueva_odc_val or not nuevo_prod_val or not nuevo_prov_val:
                                        st.warning("⚠️ El proveedor, el producto y la OC no pueden estar vacíos.")
                                    else:
                                        tiempo_actual_str = obtener_ahora_local().strftime("%Y-%m-%d %H:%M:%S")
                                        conn = sqlite3.connect("bookings.db")
                                        cursor = conn.cursor()
                                        cursor.execute(
                                            """
                                            UPDATE historico_bookings 
                                            SET proveedor = ?, producto = ?, odc = ?, familia = ?, observacion_compras = ?, ultima_modificacion = ? 
                                            WHERE id = ?
                                            """,
                                            (nuevo_prov_val, nuevo_prod_val, nueva_odc_val, nueva_fam_val, nueva_obs_compras_val, tiempo_actual_str, row["id"])
                                        )
                                        conn.commit()
                                        conn.close()
                                        st.success("¡Datos del booking actualizados con éxito!")
                                        st.rerun()

                        # Opción para mover de día
                        with st.expander("⚙️ Mover de día"):
                            if bloquear_por_tiempo_compras:
                                st.warning("🔒 No puedes mover de día este booking porque ya pasaron las 8:00 AM del día de recepción.")
                            elif es_dia_pasado and not es_autorizado:
                                st.warning("🔒 No se puede mover de día un booking cuyo día asignado ya pasó.")
                            elif not (es_creador or es_autorizado):
                                st.warning(
                                    f"🔒 Solo el creador (`{row['usuario_windows']}`) o Almacén pueden moverlo de día."
                                )
                            else:
                                dias_futuros_disponibles = [d for d in DIAS_SEMANA if dias_map[d] >= dia_actual_idx]
                                if row["dia_asignado"] not in dias_futuros_disponibles:
                                    dias_futuros_disponibles.append(row["dia_asignado"])
                                    dias_futuros_disponibles = sorted(dias_futuros_disponibles, key=lambda x: dias_map[x])

                                nuevo_dia = st.selectbox(
                                    "Cambiar al día:",
                                    dias_futuros_disponibles,
                                    index=dias_futuros_disponibles.index(row["dia_asignado"]) if row["dia_asignado"] in dias_futuros_disponibles else 0,
                                    key=f"cambiar_dia_{key_suf}{row['id']}",
                                )
                                if nuevo_dia != row["dia_asignado"]:
                                    dia_origen = row["dia_asignado"]
                                    tiempo_actual_str = obtener_ahora_local().strftime("%Y-%m-%d %H:%M:%S")
                                    conn = sqlite3.connect("bookings.db")
                                    cursor = conn.cursor()

                                    if es_autorizado and not es_creador:
                                        aviso_nuevo = f"🔄 [MOVIDO POR ALMACÉN: {usuario_actual}] Reprogramado desde {dia_origen} hacia {nuevo_dia}"
                                    else:
                                        aviso_nuevo = f"🔄 Reprogramado desde {dia_origen} hacia {nuevo_dia} por {usuario_actual}"

                                    if obs_compras_actual:
                                        nueva_nota_final = f"{obs_compras_actual} | {aviso_nuevo}"
                                    else:
                                        nueva_nota_final = aviso_nuevo

                                    cursor.execute(
                                        """UPDATE historico_bookings SET dia_asignado = ?, observacion_compras = ?, ultima_modificacion = ? WHERE id = ?""",
                                        (nuevo_dia, nueva_nota_final, tiempo_actual_str, row["id"]),
                                    )
                                    conn.commit()
                                    conn.close()
                                    st.success(f"¡Movido de {dia_origen} a {nuevo_dia} con éxito!")
                                    st.rerun()

                        # Opción para eliminar del Booking
                        with st.expander("🗑️ Eliminar del Booking"):
                            if bloquear_por_tiempo_compras:
                                st.warning("🔒 No puedes eliminar este booking después de las 8:00 AM del día de recepción.")
                            elif es_dia_pasado:
                                st.warning("🔒 No se puede eliminar un booking de un día que ya pasó.")
                            elif not es_creador:
                                st.warning(
                                    f"🔒 Solo el usuario que registró este booking (`{row['usuario_windows']}`) puede eliminarlo."
                                )
                            elif rec_val:
                                st.error("❌ Este booking ya fue recibido en almacén; no se puede eliminar.")
                            else:
                                st.warning("⚠️ Esto ocultará el proveedor del calendario semanal, pero quedará registrado en el histórico.")
                                if st.button("Confirmar Eliminación", key=f"btn_eliminar_{key_suf}{row['id']}"):
                                    tiempo_actual_str = obtener_ahora_local().strftime("%Y-%m-%d %H:%M:%S")
                                    conn = sqlite3.connect("bookings.db")
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        """UPDATE historico_bookings SET eliminado = 1, ultima_modificacion = ? WHERE id = ?""",
                                        (tiempo_actual_str, row["id"])
                                    )
                                    conn.commit()
                                    conn.close()
                                    st.success("¡El proveedor ha sido marcado como eliminado del booking!")
                                    st.rerun()

                        texto_pie = f"🕒 Reg: {row['fecha_registro']}"
                        if row["ultima_modificacion"]:
                            texto_pie += f" | 🔄 Mod: {row['ultima_modificacion']}"
                        texto_pie += f" | 👤 {row['usuario_windows']}"

                        st.caption(texto_pie)

                for _, row in df_a_tiempo.iterrows():
                    renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=False)

                for _, row in df_tarde.iterrows():
                    renderizar_tarjeta(row, es_fuera_de_tiempo_grupo=True)

            elif df_dia.empty and df_dia_eliminados.empty:
                st.info("Sin booking asignado")

    st.divider()

    # Formulario de Registro
    st.subheader("📝 Registrar Nueva Orden de Compra (Booking)")

    if es_autorizado:
        st.warning("🔒 **Acceso restringido:** Los usuarios con perfil de Almacén no pueden registrar nuevas órdenes de compra (bookings). Esta función está reservada exclusivamente para el departamento de Compras.")
    else:
        col1, col2, col3 = st.columns(3)

        with col1:
            if not dias_permitidos_edicion:
                st.error("⚠️ La semana operativa ha concluido o los días hábiles de la semana actual ya pasaron. No se pueden registrar nuevos bookings.")
                dias_disponibles_form = ["Viernes"]
            else:
                dias_disponibles_form = dias_permitidos_edicion

            dia_asignado = st.selectbox(
                "Despacho Estimado (Día)", dias_disponibles_form, key="form_dia"
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

        enviar = st.button("Guardar y Registrar Booking", key="btn_guardar_booking", disabled=not dias_permitidos_edicion)

        if enviar:
            if not dias_permitidos_edicion:
                st.error("❌ No puedes registrar bookings para días que ya pasaron.")
            elif not odc or not producto or not proveedor:
                st.warning("⚠️ Por favor completa el Producto, la OC y el Proveedor.")
            else:
                fecha_registro_str = ahora.strftime("%Y-%m-%d %H:%M:%S")

                dia_asignado_idx = dias_map.get(dia_asignado)
                es_mismo_dia = dia_asignado_idx == dia_actual_idx
                es_despues_de_8am = hora_actual > time(8, 0)
                fuera_de_tiempo = 1 if (es_mismo_dia and es_despues_de_8am) else 0

                conn = sqlite3.connect("bookings.db")
                cursor = conn.cursor()
                cursor.execute(
                    """
                        INSERT INTO historico_bookings 
                        (fecha_registro, semana, dia_asignado, familia, proveedor, producto, odc, observacion_compras, usuario_windows, fuera_de_tiempo, eliminado, ultima_modificacion)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
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
                        fecha_registro_str,
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
# 3. VISTA: HISTÓRICO GENERAL Y REPORTES (EXCEL REAL .XLSX)
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
            "ultima_modificacion",
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
            "ULTIMA MODIFICACION",
        ]
        
        df_excel_gen["RECEPCION ALMACEN"] = df_excel_gen["RECEPCION ALMACEN"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )
        df_excel_gen["ELIMINADO"] = df_excel_gen["ELIMINADO"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )

        # Generar archivo Excel (.xlsx) real en memoria usando BytesIO y ExcelWriter
        output_gen = io.BytesIO()
        with pd.ExcelWriter(output_gen, engine="openpyxl") as writer:
            df_excel_gen.to_excel(writer, index=False, sheet_name=nombre_hoja)
        excel_data_gen = output_gen.getvalue()

        st.download_button(
            label=label_boton,
            data=excel_data_gen,
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
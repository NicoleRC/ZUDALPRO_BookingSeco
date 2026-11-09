from datetime import datetime, time
import io
import os
import sqlite3
import pandas as pd
import streamlit as st

# Configuración de la página
st.set_page_config(
    page_title="Booking ZUDALPRO - Almacén Seco", page_icon="📅", layout="wide"
)


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
            fuera_de_tiempo INTEGER DEFAULT 0
        )
    """)

  columnas_nuevas = [
      ("familia", "TEXT"),
      ("producto", "TEXT"),
      ("observacion_compras", "TEXT"),
      ("recepcion_almacen", "INTEGER DEFAULT 0"),
      ("observacion_almacen", "TEXT"),
      ("fuera_de_tiempo", "INTEGER DEFAULT 0"),
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

# Identificar usuario de Windows actual
try:
  usuario_windows = os.environ.get("USERNAME", os.getlogin()).lower()
except:
  usuario_windows = "usuario_local"

# Permisos: lsuarez y kmoreno gestionan recepción y almacén
USUARIOS_AUTORIZADOS = ["lsuarez", "kmoreno"]
es_autorizado = usuario_windows in USUARIOS_AUTORIZADOS

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
        f"👤 Usuario conectado: `{usuario_windows}` (Modo lectura para campos"
        " de almacén)"
    )
  else:
    st.success(
        f"🔐 Usuario autorizado con privilegios de almacén:"
        f" `{usuario_windows}`"
    )

  # Consultar registros de la semana actual
  conn = sqlite3.connect("bookings.db")
  df_semana_actual = pd.read_sql_query(
      "SELECT * FROM historico_bookings WHERE semana = ?",
      conn,
      params=(semana_actual_str,),
  )
  conn.close()

  cols = st.columns(5)

  for i, dia in enumerate(DIAS_SEMANA):
    with cols[i]:
      st.markdown(f"### **{dia}**")
      df_dia = df_semana_actual[df_semana_actual["dia_asignado"] == dia]

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

      if not df_dia.empty:
        df_a_tiempo = df_dia[df_dia["fuera_de_tiempo"] == 0]
        df_tarde = df_dia[df_dia["fuera_de_tiempo"] == 1]

        # 1. Registros a tiempo
        for _, row in df_a_tiempo.iterrows():
          rec_val = bool(row["recepcion_almacen"])
          obs_alm = row["observacion_almacen"] or ""
          obs_compras_actual = (
              str(row["observacion_compras"])
              if pd.notna(row["observacion_compras"])
              else ""
          )

          # Validar si el usuario actual es el creador del registro
          es_creador = str(row["usuario_windows"]).lower() == usuario_windows

          with st.container(border=True):
            st.markdown(
                f"**{row['proveedor']}**\n\n*Prod:* {row['producto']}\n*OC:* `{row['odc']}`"
                f" | *Fam:* {row['familia']}"
            )
            if obs_compras_actual:
              st.text(f"Obs Compras: {obs_compras_actual}")

            nuevo_rec = st.checkbox(
                "Recibido Almacén",
                value=rec_val,
                key=f"rec_{row['id']}",
                disabled=not es_autorizado,
            )
            nueva_obs_alm = st.text_input(
                "Obs. Almacén",
                value=obs_alm,
                key=f"obs_alm_{row['id']}",
                disabled=not es_autorizado,
            )

            if es_autorizado and (
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

            # Opción para mover de día protegida por usuario creador
            with st.expander("⚙️ Mover de día"):
              if not es_creador:
                st.warning(
                    f"🔒 Solo el usuario que registró este booking"
                    f" (`{row['usuario_windows']}`) puede moverlo de día."
                )
              else:
                nuevo_dia = st.selectbox(
                    "Cambiar al día:",
                    DIAS_SEMANA,
                    index=DIAS_SEMANA.index(row["dia_asignado"]),
                    key=f"cambiar_dia_{row['id']}",
                )
                if nuevo_dia != row["dia_asignado"]:
                  dia_origen = row["dia_asignado"]
                  conn = sqlite3.connect("bookings.db")
                  cursor = conn.cursor()

                  aviso_nuevo = f"🔄 Reprogramado desde {dia_origen}"
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
                  st.success(f"¡Movido a {nuevo_dia} con historial actualizado!")
                  st.rerun()

            st.caption(
                f"🕒 Reg: {row['fecha_registro']} | 👤 {row['usuario_windows']}"
            )

        # 2. Registros fuera de tiempo
        for _, row in df_tarde.iterrows():
          rec_val = bool(row["recepcion_almacen"])
          obs_alm = row["observacion_almacen"] or ""
          obs_compras_actual = (
              str(row["observacion_compras"])
              if pd.notna(row["observacion_compras"])
              else ""
          )
          es_creador = str(row["usuario_windows"]).lower() == usuario_windows

          with st.container(border=True):
            st.error(
                f"🚨 **FUERA DE TIEMPO**\n\n**{row['proveedor']}**\n*Prod:*"
                f" {row['producto']}\n*OC:* `{row['odc']}`"
            )
            if obs_compras_actual:
              st.text(f"Obs Compras: {obs_compras_actual}")

            nuevo_rec = st.checkbox(
                "Recibido Almacén (Tarde)",
                value=rec_val,
                key=f"rec_t_{row['id']}",
                disabled=not es_autorizado,
            )
            nueva_obs_alm = st.text_input(
                "Obs. Almacén",
                value=obs_alm,
                key=f"obs_alm_t_{row['id']}",
                disabled=not es_autorizado,
            )

            if es_autorizado and (
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

            # Opción para mover de día protegida por usuario creador
            with st.expander("⚙️ Mover de día"):
              if not es_creador:
                st.warning(
                    f"🔒 Solo el usuario que registró este booking"
                    f" (`{row['usuario_windows']}`) puede moverlo de día."
                )
              else:
                nuevo_dia = st.selectbox(
                    "Cambiar al día:",
                    DIAS_SEMANA,
                    index=DIAS_SEMANA.index(row["dia_asignado"]),
                    key=f"cambiar_dia_t_{row['id']}",
                )
                if nuevo_dia != row["dia_asignado"]:
                  dia_origen = row["dia_asignado"]
                  conn = sqlite3.connect("bookings.db")
                  cursor = conn.cursor()

                  aviso_nuevo = f"🔄 Reprogramado desde {dia_origen}"
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
                  st.success(f"¡Movido a {nuevo_dia} con historial actualizado!")
                  st.rerun()

            st.caption(
                f"🕒 Reg: {row['fecha_registro']} | 👤 {row['usuario_windows']}"
            )
      else:
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
                (fecha_registro, semana, dia_asignado, familia, proveedor, producto, odc, observacion_compras, usuario_windows, fuera_de_tiempo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              usuario_windows,
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
    semanas_disponibles = df_todos["semana"].unique().tolist()
    semana_seleccionada = st.selectbox(
        "Selecciona la Semana a Consultar", semanas_disponibles
    )

    df_filtrado = df_todos[df_todos["semana"] == semana_seleccionada]
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
    ]
    df_excel_gen["RECEPCION ALMACEN"] = df_excel_gen["RECEPCION ALMACEN"].apply(
        lambda x: "SI" if x == 1 else "NO"
    )

    output = io.BytesIO()
    with pd.ExcelWriter(output) as writer:
      df_excel_gen.to_excel(writer, index=False, sheet_name="Historico_Semanal")
    excel_data = output.getvalue()

    st.download_button(
        label=f"📥 Descargar Reporte Completo de la {semana_seleccionada} (Excel)",
        data=excel_data,
        file_name=f"Reporte_General_{semana_seleccionada}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
  else:
    st.info("Aún no hay registros guardados en la base de datos.")
import { queryOptions } from '@tanstack/react-query'

// Cliente de la API de Python (necc.m6_visualizacion.api). Tipos = contrato de cada endpoint.

export type EstadoDocumento = 'descubierto' | 'en_cola' | 'procesando' | 'completado' | 'error'
export type EstadoValor = 'ok' | 'revisar' | 'faltante' | 'corregido'
export type Severidad = 'error' | 'advertencia' | 'info'
export type TipoCampo = 'conteo' | 'monto' | 'ratio'

export interface DocumentoResumen {
  id: number
  archivo: string
  entidad: string | null
  estado: EstadoDocumento
  fecha_balance: string | null
  unidad: string | null
  paginas: number | null
  origen: string
  a_revisar: number
  error: string | null
  actualizado_en: string
}

export interface Lectura {
  metodo: string
  valor_texto: string
  pagina: number | null
  confianza: number
  verificado: boolean
  elegido: boolean
}

export interface Campo {
  campo: string
  nombre: string
  tipo: TipoCampo
  requerido: boolean
  componente: boolean
  norma: string
  valor: number | null
  valor_origen: number | null
  metodo: string
  pagina: number | null
  evidencia: string
  confianza: number
  estado: EstadoValor
  corregido_por: string | null
  comentario: string | null
  lecturas: Lectura[]
}

export interface Incidencia {
  id: number
  campo: string | null
  regla: string
  severidad: Severidad
  mensaje: string
  estado: string
  responsable: string | null
  accion_sugerida: string
}

/** Incidencia abierta tal como la lista /api/incidencias (trae el documento al que pertenece). */
export interface IncidenciaPendiente extends Incidencia {
  documento_id: number
  entidad: string
  campo_nombre: string | null
  creado_en: string
}

export interface Etapa {
  etapa: string
  estado: 'ok' | 'error' | 'pendiente'
  detalle: string
  segundos: number | null
}

export interface DocumentoDetalle extends DocumentoResumen {
  evidencia_unidad: string | null
  paginas_seleccionadas: number[]
  campos: Campo[]
  incidencias: Incidencia[]
  progreso: Etapa[]
}

export interface FilaTablero {
  documento_id: number
  entidad: string
  fecha_balance: string
  valores: Record<string, number | null>
  reserva_por_juicio: number | null
  pct_con_pagos_parciales: number | null
}

export interface Tablero {
  campos: { campo: string; nombre: string; tipo: TipoCampo; requerido: boolean }[]
  filas: FilaTablero[]
  kpis: { entidades: number; juicios_abiertos: number; reserva_total: number; a_revisar: number }
}

export interface Fuente {
  documento_id: number
  entidad: string
  pagina: number
  extracto: string
}

export interface Responsable {
  id: string
  nombre: string
  email?: string
  slack?: string
}

export interface Accion {
  id: number
  documento_id: number | null
  tipo: string
  canal: string
  destinatario: string
  asunto: string
  cuerpo: string
  estado: string
  creado_en: string
}

export interface Registro {
  id: number
  archivo: string
  nuevo: boolean
}

/** Raíz de la API según la base del build (`vite build --base`): la interfaz puede servirse bajo un subdirectorio. */
export const API = `${import.meta.env.BASE_URL}api`

async function pedir<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(url, init)
  } catch {
    throw new Error('No se pudo conectar con la API. ¿Está corriendo `uv run necc ui`?')
  }
  if (!r.ok) {
    const cuerpo: { detail?: unknown } = await r.json().catch(() => ({}))
    throw new Error(typeof cuerpo.detail === 'string' ? cuerpo.detail : `La API respondió con error ${r.status}.`)
  }
  return r.json() as Promise<T>
}

const json = (cuerpo: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(cuerpo),
})

export const api = {
  config: () => pedir<{ demo: boolean }>(`${API}/config`),
  documentos: () => pedir<DocumentoResumen[]>(`${API}/documentos`),
  documento: (id: number) => pedir<DocumentoDetalle>(`${API}/documentos/${id}`),
  subir: (archivos: File[]) => {
    const datos = new FormData()
    archivos.forEach((a) => datos.append('archivos', a))
    return pedir<Registro[]>(`${API}/documentos`, { method: 'POST', body: datos })
  },
  descubrir: () => pedir<Registro[]>(`${API}/descubrir`, { method: 'POST' }),
  reprocesar: (id: number) => pedir<{ id: number; estado: EstadoDocumento }>(`${API}/documentos/${id}/procesar`, { method: 'POST' }),
  aprobar: (id: number, campo: string, usuario: string) =>
    pedir<{ ok: boolean }>(`${API}/documentos/${id}/valores/${campo}/aprobar`, json({ usuario })),
  corregir: (id: number, campo: string, usuario: string, valor: number, comentario: string) =>
    pedir<{ ok: boolean }>(`${API}/documentos/${id}/valores/${campo}/corregir`, json({ usuario, valor, comentario })),
  tablero: () => pedir<Tablero>(`${API}/tablero`),
  consultar: (pregunta: string) =>
    pedir<{ respuesta: string; fuentes: Fuente[] }>(`${API}/consulta`, json({ pregunta })),
  incidencias: () => pedir<IncidenciaPendiente[]>(`${API}/incidencias`),
  responsables: () => pedir<Responsable[]>(`${API}/responsables`),
  etiquetar: (id: number, responsable: string, nota: string, autor: string) =>
    pedir<{ canales: string[] }>(`${API}/incidencias/${id}/etiquetar`, json({ responsable, nota, autor })),
  resolver: (id: number, estado: 'resuelta' | 'descartada', usuario: string) =>
    pedir<{ ok: boolean }>(`${API}/incidencias/${id}/resolver`, json({ estado, usuario })),
  acciones: () => pedir<Accion[]>(`${API}/acciones`),
  reporte: () => pedir<{ markdown: string }>(`${API}/reportes/consolidado`, { method: 'POST' }),
}

/** Configuración del servidor; `demo` llega `undefined` mientras carga. */
export const consultaConfig = queryOptions({ queryKey: ['config'], queryFn: api.config, staleTime: Infinity })

export function urlPagina(id: number, pagina: number, resaltar?: string, recorte = false): string {
  const params = new URLSearchParams()
  if (resaltar) params.set('resaltar', resaltar)
  if (recorte) params.set('recorte', 'true')
  return `${API}/documentos/${id}/paginas/${pagina}?${params}`
}

import { CircleNotch, WarningCircle } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'
import { consultaConfig, type EstadoDocumento, type EstadoValor, type Severidad } from '../api'
import { useUsuario } from '../usuario'

type Tono = 'ok' | 'warn' | 'bad' | 'info' | 'neutro'

const TONOS: Record<Tono, string> = {
  ok: 'bg-ok-bg text-ok',
  warn: 'bg-warn-bg text-warn',
  bad: 'bg-bad-bg text-bad',
  info: 'bg-info-bg text-info',
  neutro: 'bg-subtle text-muted',
}

export function Badge({ tono = 'neutro', children }: { tono?: Tono; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.05em] ${TONOS[tono]}`}
    >
      {children}
    </span>
  )
}

const ESTADO_VALOR: Record<EstadoValor, [Tono, string]> = {
  ok: ['ok', 'OK'],
  revisar: ['warn', 'Revisar'],
  faltante: ['bad', 'Faltante'],
  corregido: ['info', 'Validado'],
}

export function EstadoValorBadge({ estado, opcional }: { estado: EstadoValor; opcional?: boolean }) {
  if (estado === 'faltante' && opcional) return <Badge>No informado</Badge>
  const [tono, texto] = ESTADO_VALOR[estado]
  return <Badge tono={tono}>{texto}</Badge>
}

const ESTADO_DOC: Record<EstadoDocumento, [Tono, string]> = {
  descubierto: ['neutro', 'Registrado'],
  en_cola: ['neutro', 'En cola'],
  procesando: ['info', 'Procesando'],
  completado: ['ok', 'Listo'],
  error: ['bad', 'Error'],
}

export function EstadoDocumentoBadge({ estado }: { estado: EstadoDocumento }) {
  const [tono, texto] = ESTADO_DOC[estado]
  return (
    <Badge tono={tono}>
      {(estado === 'procesando' || estado === 'en_cola') && <CircleNotch className="animate-spin" size={10} weight="bold" />}
      {texto}
    </Badge>
  )
}

const SEVERIDAD: Record<Severidad, Tono> = { error: 'bad', advertencia: 'warn', info: 'info' }

export function SeveridadBadge({ severidad }: { severidad: Severidad }) {
  return <Badge tono={SEVERIDAD[severidad]}>{severidad}</Badge>
}

type Variante = 'primario' | 'secundario' | 'fantasma'

const VARIANTES: Record<Variante, string> = {
  primario: 'bg-ink-strong text-white hover:bg-[#333]',
  secundario: 'border border-line bg-surface text-ink hover:bg-subtle',
  fantasma: 'text-muted hover:bg-subtle hover:text-ink',
}

const BASE_BOTON =
  'inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition active:scale-[0.98]'

export function Boton({
  variante = 'secundario',
  cargando,
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; cargando?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || cargando}
      className={`${BASE_BOTON} disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTES[variante]} ${className}`}
    >
      {cargando && <CircleNotch className="animate-spin" size={14} weight="bold" />}
      {children}
    </button>
  )
}

/** Enlace con aspecto de botón (descargas, archivos): evita anidar un <button> dentro de un <a>. */
export function BotonEnlace({
  variante = 'secundario',
  className = '',
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { variante?: Variante }) {
  return <a {...props} className={`${BASE_BOTON} ${VARIANTES[variante]} ${className}`} />
}

export function Tarjeta({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-[10px] border border-line bg-surface ${className}`}>{children}</div>
}

export function Encabezado({ titulo, bajada, acciones }: { titulo: string; bajada?: ReactNode; acciones?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-[40px] leading-[1.1] tracking-[-0.02em] text-ink-strong">{titulo}</h1>
        {bajada && <p className="mt-2 max-w-2xl text-[15px] text-muted">{bajada}</p>}
      </div>
      {acciones && <div className="flex gap-2">{acciones}</div>}
    </div>
  )
}

export function Cargando() {
  return (
    <div role="status" className="flex items-center gap-2 py-16 text-sm text-muted">
      <CircleNotch className="animate-spin" size={16} /> Cargando…
    </div>
  )
}

export function Vacio({ children }: { children: ReactNode }) {
  return <div className="rounded-[10px] border border-dashed border-line px-6 py-12 text-center text-sm text-muted">{children}</div>
}

export function Fallo({ error, className = '' }: { error: Error | null; className?: string }) {
  if (!error) return null
  return (
    <p role="alert" className={`flex items-start gap-2 text-sm text-bad ${className}`}>
      <WarningCircle size={16} weight="bold" className="mt-0.5 shrink-0" />
      {error.message}
    </p>
  )
}

export const campoTexto =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none transition placeholder:text-muted focus:border-ink/40'

export function CampoUsuario({ className = '' }: { className?: string }) {
  const [usuario, setUsuario] = useUsuario()
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs text-muted">Revisás como</span>
      <input
        className={campoTexto}
        placeholder="Tu nombre (queda registrado)"
        autoComplete="name"
        value={usuario}
        onChange={(e) => setUsuario(e.target.value)}
      />
    </label>
  )
}

/** Controles que escriben en el servidor: se ocultan en la demo pública y mientras no se sabe si lo es. */
export function Editable({ children }: { children: ReactNode }) {
  const { data } = useQuery(consultaConfig)
  return data?.demo === false ? children : null
}

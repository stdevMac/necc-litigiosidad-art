import type { TipoCampo } from './api'

const entero = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 })
const decimal = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
const unDecimal = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 })
const porcentaje = new Intl.NumberFormat('es-AR', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })
const editable = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 6 })

export function valor(v: number | null | undefined, tipo: TipoCampo = 'monto'): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (tipo === 'ratio') return decimal.format(v)
  return entero.format(v)
}

export function pesos(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `$ ${entero.format(v)}`
}

/** Montos grandes abreviados: $ 754.998 M; debajo de 100 M se conserva un decimal ($ 1,5 M). */
export function pesosEnMillones(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const m = v / 1e6
  return `$ ${(Math.abs(m) < 100 ? unDecimal : entero).format(m)} M`
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : porcentaje.format(v)
}

export function fecha(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${a}`
}

/** 2026-10-14T13:28:05 → 14/10/2026 13:28 */
export function fechaHora(iso: string): string {
  return `${fecha(iso)} ${iso.slice(11, 16)}`
}

/** Valor listo para editar a mano, en formato argentino (6.197.244.842 · 0,3769). */
export function textoEditable(v: number | null): string {
  return v === null ? '' : editable.format(v)
}

/**
 * Interpreta un número escrito en formato argentino: punto de miles y coma decimal.
 * En los ratios sin coma el punto se toma como decimal (0.37), que es como se suele tipear.
 */
export function leerNumero(texto: string, tipo: TipoCampo): number | null {
  const limpio = texto.replace(/[$\s]/g, '')
  const normal = limpio.includes(',') || tipo !== 'ratio' ? limpio.replace(/\./g, '').replace(',', '.') : limpio
  return /^-?\d+(\.\d+)?$/.test(normal) ? Number(normal) : null
}

const SIGLAS: Record<string, true> = { ART: true, 'A.R.T.': true, 'S.A.': true, 'S.A': true, SA: true, SRL: true, 'S.R.L.': true }
const MENORES: Record<string, true> = { de: true, del: true, la: true, las: true, los: true, y: true, e: true }

/** Las notas escriben la razón social en mayúsculas; para leerla se pasa a tipo título sin tocar siglas. */
export function entidad(nombre: string | null | undefined): string {
  if (!nombre) return ''
  if (nombre !== nombre.toUpperCase()) return nombre
  return nombre
    .split(/\s+/)
    .map((palabra, k) => {
      const minuscula = palabra.toLowerCase()
      if (SIGLAS[palabra]) return palabra
      if (k > 0 && MENORES[minuscula]) return minuscula
      return minuscula.charAt(0).toUpperCase() + minuscula.slice(1)
    })
    .join(' ')
}

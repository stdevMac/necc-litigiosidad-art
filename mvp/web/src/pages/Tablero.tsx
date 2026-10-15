import { DownloadSimple } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type YAxisTickContentProps } from 'recharts'
import { API, api, type FilaTablero, type Tablero as DatosTablero } from '../api'
import { BotonEnlace, Cargando, Encabezado, Fallo, Tarjeta, Vacio } from '../components/ui'
import { entidad, fecha, pct, pesosEnMillones, valor } from '../formato'

const LARGO_ETIQUETA = 30

export function Tablero() {
  const { data, isLoading, error } = useQuery({ queryKey: ['tablero'], queryFn: api.tablero })

  return (
    <>
      <Encabezado
        titulo="Tablero"
        bajada="Indicadores de litigiosidad estandarizados, en pesos, una fila por entidad y fecha de balance."
        acciones={
          <BotonEnlace variante="primario" href={`${API}/exportar`} download>
            <DownloadSimple size={16} weight="bold" /> Descargar Excel base
          </BotonEnlace>
        }
      />
      {isLoading ? (
        <Cargando />
      ) : !data ? (
        <Fallo error={error} />
      ) : !data.filas.length ? (
        <Vacio>Todavía no hay documentos procesados.</Vacio>
      ) : (
        <Contenido {...data} />
      )}
    </>
  )
}

function Contenido({ filas, kpis, campos }: DatosTablero) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi titulo="Entidades" valor={valor(kpis.entidades)} />
        <Kpi titulo="Juicios abiertos" valor={valor(kpis.juicios_abiertos)} />
        <Kpi titulo="Reserva por reclamaciones" valor={pesosEnMillones(kpis.reserva_total)} />
        <Kpi titulo="Puntos a revisar" valor={valor(kpis.a_revisar)} destacado={kpis.a_revisar > 0} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Grafico titulo="Juicios abiertos" filas={filas} dato={(f) => f.valores.juicios_abiertos} formato={valor} />
        <Grafico titulo="Reserva promedio por juicio" filas={filas} dato={(f) => f.reserva_por_juicio} formato={pesosEnMillones} />
        <Grafico titulo="Juicios con pagos parciales" filas={filas} dato={(f) => f.pct_con_pagos_parciales} formato={pct} />
        <Grafico
          titulo="Ratio juicios cerrados / stock (12 meses)"
          filas={filas}
          dato={(f) => f.valores.ratio_cerrados_stock}
          formato={(v) => valor(v, 'ratio')}
        />
      </div>

      <h2 className="mb-3 mt-12 text-xs font-medium uppercase tracking-[0.08em] text-muted">Excel base</h2>
      <Tarjeta className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th scope="col" className="sticky left-0 bg-surface px-4 py-3 font-medium">
                Entidad
              </th>
              {campos.map((c) => (
                <th scope="col" key={c.campo} className="min-w-36 px-4 py-3 text-right align-bottom font-medium leading-snug">
                  {c.nombre}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {filas.map((f) => (
              <tr key={f.documento_id} className="group">
                <th scope="row" className="sticky left-0 max-w-64 bg-surface px-4 py-3 text-left font-normal group-hover:bg-canvas">
                  <Link
                    to={`/documentos/${f.documento_id}`}
                    className="block truncate text-ink-strong hover:underline"
                    title={entidad(f.entidad)}
                  >
                    {entidad(f.entidad)}
                  </Link>
                  <span className="num text-xs text-muted">al {fecha(f.fecha_balance)}</span>
                </th>
                {campos.map((c) => (
                  <td key={c.campo} className="num px-4 py-3 text-right font-mono text-[13px] group-hover:bg-canvas">
                    {valor(f.valores[c.campo], c.tipo)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Tarjeta>
      <p className="mt-2 text-xs text-muted">Montos en pesos. “—” indica que la entidad no informa el dato.</p>
    </>
  )
}

function Kpi({ titulo, valor, destacado }: { titulo: string; valor: string; destacado?: boolean }) {
  return (
    <Tarjeta className="px-5 py-4">
      <p className="text-xs text-muted">{titulo}</p>
      <p className={`num mt-1 font-serif text-[32px] leading-tight ${destacado ? 'text-warn' : 'text-ink-strong'}`}>{valor}</p>
    </Tarjeta>
  )
}

interface Punto {
  entidad: string
  completa: string
  v: number
}

function Grafico({
  titulo,
  filas,
  dato,
  formato,
}: {
  titulo: string
  filas: FilaTablero[]
  dato: (f: FilaTablero) => number | null
  formato: (v: number) => string
}) {
  const serie = filas
    .flatMap((f): Punto[] => {
      const v = dato(f)
      if (v === null) return []
      const completa = entidad(f.entidad)
      const corta = completa.length > LARGO_ETIQUETA ? `${completa.slice(0, LARGO_ETIQUETA - 1).trimEnd()}…` : completa
      return [{ entidad: corta, completa, v }]
    })
    .sort((a, b) => b.v - a.v)

  return (
    <Tarjeta className="px-5 pb-3 pt-4">
      <p className="mb-3 text-sm text-ink-strong">{titulo}</p>
      {serie.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">Ninguna entidad lo informa.</p>
      ) : (
        <ResponsiveContainer width="100%" height={serie.length * 34 + 10}>
          <BarChart data={serie} layout="vertical" margin={{ left: 0, right: 64, top: 0, bottom: 0 }} accessibilityLayer>
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="entidad"
              width={210}
              tickLine={false}
              axisLine={false}
              tick={({ x, y, payload }: YAxisTickContentProps) => (
                <text x={x} y={y} dy={4} textAnchor="end" fontSize={12} fill="#787774">
                  {payload.value}
                </text>
              )}
            />
            <Tooltip
              cursor={{ fill: '#f7f6f3' }}
              labelFormatter={(_, p) => (p[0]?.payload as Punto | undefined)?.completa ?? ''}
              formatter={(v) => [formato(Number(v)), titulo]}
              contentStyle={{ border: '1px solid #eaeaea', borderRadius: 8, fontSize: 12, boxShadow: 'none' }}
            />
            <Bar
              dataKey="v"
              fill="#2f3437"
              radius={[0, 3, 3, 0]}
              barSize={14}
              label={{ position: 'right', fontSize: 11, fill: '#2f3437', formatter: (v: unknown) => formato(Number(v)) }}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Tarjeta>
  )
}

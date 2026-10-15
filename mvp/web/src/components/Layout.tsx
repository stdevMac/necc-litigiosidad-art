import { useQuery } from '@tanstack/react-query'
import { Suspense } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, consultaConfig } from '../api'
import { Cargando } from './ui'

const SECCIONES = [
  { a: '/', texto: 'Documentos' },
  { a: '/tablero', texto: 'Tablero' },
  { a: '/consulta', texto: 'Consulta' },
  { a: '/acciones', texto: 'Acciones' },
]

export function Layout() {
  const { data: incidencias } = useQuery({ queryKey: ['incidencias'], queryFn: api.incidencias, refetchInterval: 15000 })
  const { data: config } = useQuery(consultaConfig)

  return (
    <div className="min-h-screen">
      {config?.demo && (
        <p className="border-b border-line bg-subtle px-8 py-1.5 text-center text-xs text-muted">
          Demo pública de solo lectura con las 6 notas de ejemplo. Las consultas tienen un tope diario.
        </p>
      )}
      <header className="sticky top-0 z-10 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-10 px-8">
          <NavLink to="/" className="flex items-baseline gap-2">
            <span className="font-serif text-2xl leading-none text-ink-strong">NECC</span>
            <span className="text-[13px] text-muted">Litigiosidad ART</span>
          </NavLink>
          <nav aria-label="Secciones" className="flex gap-1">
            {SECCIONES.map((s) => (
              <NavLink
                key={s.a}
                to={s.a}
                end={s.a === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition ${
                    isActive ? 'bg-subtle text-ink-strong' : 'text-muted hover:text-ink'
                  }`
                }
              >
                {s.texto}
                {s.a === '/acciones' && !!incidencias?.length && (
                  <span
                    className="num rounded-full bg-warn-bg px-1.5 text-[11px] font-medium text-warn"
                    aria-label={`${incidencias.length} pendientes`}
                  >
                    {incidencias.length}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-8 pb-24 pt-12">
        <Suspense fallback={<Cargando />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}

import { At, CaretRight, Check, FileText, X } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import Markdown from 'react-markdown'
import { Link } from 'react-router-dom'
import remarkGfm from 'remark-gfm'
import { api, type IncidenciaPendiente, type Responsable } from '../api'
import { Badge, Boton, CampoUsuario, campoTexto, Cargando, Editable, Encabezado, Fallo, SeveridadBadge, Tarjeta, Vacio } from '../components/ui'
import { entidad, fechaHora } from '../formato'
import { useUsuario } from '../usuario'

const TIPO_ACCION: Record<string, string> = { notificacion: 'Aviso', etiqueta: 'Etiqueta', reporte: 'Reporte' }
const CANAL: Record<string, string> = { bandeja: 'bandeja local', slack: 'Slack', email: 'correo' }

export function Acciones() {
  const cliente = useQueryClient()
  const { data: incidencias, isLoading, error } = useQuery({ queryKey: ['incidencias'], queryFn: api.incidencias })
  const { data: responsables = [] } = useQuery({ queryKey: ['responsables'], queryFn: api.responsables })
  const acciones = useQuery({ queryKey: ['acciones'], queryFn: api.acciones })
  const reporte = useMutation({
    mutationFn: api.reporte,
    onSuccess: () => cliente.invalidateQueries({ queryKey: ['acciones'] }),
  })

  return (
    <>
      <Encabezado
        titulo="Acciones"
        bajada="Lo que el sistema no pudo cerrar solo. Cada punto tiene un responsable y una acción concreta; se puede etiquetar a otra persona o cerrarlo."
        acciones={
          <Editable>
            <Boton onClick={() => reporte.mutate()} cargando={reporte.isPending}>
              <FileText size={16} weight="bold" /> Enviar reporte consolidado
            </Boton>
          </Editable>
        }
      />

      <Fallo error={reporte.error} className="mb-6" />
      {reporte.data && (
        <Tarjeta className="prosa mb-8 overflow-x-auto px-6 py-5 text-sm">
          <Markdown remarkPlugins={[remarkGfm]}>{reporte.data.markdown}</Markdown>
          <p className="mt-3 text-xs text-muted">Enviado al responsable de reportes; queda registrado en Notificaciones enviadas.</p>
        </Tarjeta>
      )}

      <div className="mb-3 flex flex-wrap items-end justify-between gap-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">Pendientes</h2>
        {!!incidencias?.length && (
          <Editable>
            <CampoUsuario className="w-64" />
          </Editable>
        )}
      </div>
      {isLoading ? (
        <Cargando />
      ) : error ? (
        <Fallo error={error} />
      ) : !incidencias?.length ? (
        <Vacio>No hay nada pendiente de revisión.</Vacio>
      ) : (
        <div className="space-y-3">
          {incidencias.map((i) => (
            <TarjetaIncidencia key={i.id} incidencia={i} responsables={responsables} />
          ))}
        </div>
      )}

      <h2 className="mb-3 mt-14 text-xs font-medium uppercase tracking-[0.08em] text-muted">Notificaciones enviadas</h2>
      {acciones.isLoading ? (
        <Cargando />
      ) : acciones.error ? (
        <Fallo error={acciones.error} />
      ) : !acciones.data?.length ? (
        <Vacio>Todavía no se envió ninguna notificación.</Vacio>
      ) : (
        <Tarjeta className="divide-y divide-line">
          {acciones.data.map((a) => (
            <details key={a.id} className="group px-5 py-3">
              <summary className="flex cursor-pointer list-none items-center gap-4 text-sm">
                <CaretRight size={12} weight="bold" className="shrink-0 text-muted transition group-open:rotate-90" />
                <span className="num w-32 shrink-0 font-mono text-xs text-muted">{fechaHora(a.creado_en)}</span>
                <span className="flex w-24 shrink-0">
                  <Badge>{TIPO_ACCION[a.tipo] ?? a.tipo}</Badge>
                </span>
                <span className="min-w-0 flex-1 truncate text-ink-strong" title={a.asunto}>
                  {a.asunto}
                </span>
                {a.estado === 'fallida' && <Badge tono="bad">Falló</Badge>}
                <span className="hidden shrink-0 text-xs text-muted md:block">
                  {a.destinatario.split(' <')[0]} · {CANAL[a.canal] ?? a.canal}
                </span>
              </summary>
              <pre className="mt-3 whitespace-pre-wrap rounded-md bg-subtle p-4 font-mono text-xs leading-relaxed text-ink">{a.cuerpo}</pre>
            </details>
          ))}
        </Tarjeta>
      )}
    </>
  )
}

function TarjetaIncidencia({ incidencia: i, responsables }: { incidencia: IncidenciaPendiente; responsables: Responsable[] }) {
  const cliente = useQueryClient()
  const [usuario] = useUsuario()
  const firma = usuario.trim()
  const [etiquetando, setEtiquetando] = useState(false)
  const [persona, setPersona] = useState('')
  const [nota, setNota] = useState('')
  const destino = persona || i.responsable || responsables[0]?.id || ''
  const refrescar = () => {
    for (const clave of ['incidencias', 'acciones', 'documentos', 'documento', 'tablero'])
      cliente.invalidateQueries({ queryKey: [clave] })
  }
  const etiquetar = useMutation({
    mutationFn: () => api.etiquetar(i.id, destino, nota.trim(), firma),
    onSuccess: () => {
      setEtiquetando(false)
      setNota('')
      refrescar()
    },
  })
  const resolver = useMutation({
    mutationFn: (estado: 'resuelta' | 'descartada') => api.resolver(i.id, estado, firma),
    onSuccess: refrescar,
  })
  const responsable = responsables.find((r) => r.id === i.responsable)
  const canales = etiquetar.data?.canales.map((c) => c.split(':')) ?? []
  const fallidos = canales.filter(([, estado]) => estado === 'fallida').map(([canal]) => CANAL[canal] ?? canal)
  const enviados = canales.filter(([, estado]) => estado !== 'fallida').map(([canal]) => CANAL[canal] ?? canal)

  return (
    <Tarjeta className="aparecer px-5 py-4">
      <div className="flex flex-wrap items-start gap-4">
        <SeveridadBadge severidad={i.severidad} />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted">
            <Link to={`/documentos/${i.documento_id}`} className="text-ink-strong hover:underline">
              {entidad(i.entidad)}
            </Link>
            {i.campo_nombre ? ` · ${i.campo_nombre}` : ''}
          </p>
          <p className="mt-1 text-[15px] text-ink-strong">{i.mensaje}</p>
          <p className="mt-2 text-sm text-muted">{i.accion_sugerida}</p>
          <p className="mt-2 text-xs text-muted">Responsable: {responsable?.nombre ?? 'sin asignar'}</p>
        </div>
        <Editable>
          <div className="flex gap-1.5">
            <Boton
              variante="fantasma"
              onClick={() => setEtiquetando((v) => !v)}
              aria-expanded={etiquetando}
              title="Avisarle a una persona"
            >
              <At size={15} weight="bold" /> Etiquetar
            </Boton>
            <Boton
              variante="fantasma"
              onClick={() => resolver.mutate('descartada')}
              disabled={!firma || resolver.isPending}
              cargando={resolver.isPending && resolver.variables === 'descartada'}
              title="Descartar: no aplica"
              aria-label="Descartar: no aplica"
            >
              {!(resolver.isPending && resolver.variables === 'descartada') && <X size={15} weight="bold" />}
            </Boton>
            <Boton
              onClick={() => resolver.mutate('resuelta')}
              disabled={!firma || resolver.isPending}
              cargando={resolver.isPending && resolver.variables === 'resuelta'}
            >
              <Check size={15} weight="bold" /> Resuelta
            </Boton>
          </div>
        </Editable>
      </div>
      <Editable>
        {!firma && <p className="mt-2 text-right text-xs text-muted">Escribí tu nombre arriba para cerrar o etiquetar.</p>}
      </Editable>

      {etiquetando && (
        <form
          className="mt-4 grid gap-2 border-t border-line pt-4 sm:grid-cols-[220px_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            if (firma && destino && nota.trim()) etiquetar.mutate()
          }}
        >
          <select className={campoTexto} aria-label="Persona a avisar" value={destino} onChange={(e) => setPersona(e.target.value)}>
            {responsables.map((r) => (
              <option key={r.id} value={r.id}>
                {r.nombre}
              </option>
            ))}
          </select>
          <input
            className={campoTexto}
            aria-label="Mensaje"
            placeholder="Mensaje, por ejemplo: ¿podés confirmarlo antes del cierre?"
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            autoFocus
          />
          <Boton variante="primario" type="submit" cargando={etiquetar.isPending} disabled={!firma || !destino || !nota.trim()}>
            Enviar
          </Boton>
        </form>
      )}
      {enviados.length > 0 && <p className="mt-2 text-xs text-ok">Notificado por {enviados.join(', ')}.</p>}
      {fallidos.length > 0 && <p className="mt-2 text-xs text-bad">No se pudo notificar por {fallidos.join(', ')}.</p>}
      <Fallo error={etiquetar.error ?? resolver.error} className="mt-2" />
    </Tarjeta>
  )
}

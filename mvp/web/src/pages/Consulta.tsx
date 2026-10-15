import { ArrowUp } from '@phosphor-icons/react'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import Markdown from 'react-markdown'
import { Link } from 'react-router-dom'
import remarkGfm from 'remark-gfm'
import { api, urlPagina, type Fuente } from '../api'
import { Boton, campoTexto, Encabezado, Fallo, Tarjeta } from '../components/ui'
import { entidad } from '../formato'

const SUGERENCIAS = [
  '¿Qué entidad tiene la mayor reserva promedio por juicio?',
  '¿Cómo valúa Prevención ART los juicios anteriores a 2017?',
  '¿Qué dice la nota sobre el Fondo Fiduciario de Enfermedades Profesionales?',
]

interface Turno {
  pregunta: string
  respuesta?: string
  fuentes?: Fuente[]
  error?: Error
}

export function Consulta() {
  const [turnos, setTurnos] = useState<Turno[]>([])
  const [texto, setTexto] = useState('')
  const consultar = useMutation({
    mutationFn: api.consultar,
    onSuccess: (r) => setTurnos((t) => [...t.slice(0, -1), { ...t[t.length - 1], ...r }]),
    onError: (error) => setTurnos((t) => [...t.slice(0, -1), { ...t[t.length - 1], error }]),
  })

  const preguntar = (pregunta: string) => {
    const limpia = pregunta.trim()
    if (!limpia || consultar.isPending) return
    setTurnos((t) => [...t, { pregunta: limpia }])
    setTexto('')
    consultar.mutate(limpia)
  }

  return (
    <div className="mx-auto max-w-3xl">
      <Encabezado
        titulo="Consulta"
        bajada="Preguntá en lenguaje natural. Las respuestas salen solo de los documentos cargados y de la tabla estandarizada, con la página citada."
      />

      <div className="space-y-8" aria-live="polite">
        {turnos.map((t, k) => (
          <div key={k} className="aparecer space-y-3">
            <p className="text-[15px] text-ink-strong">{t.pregunta}</p>
            {t.respuesta ? (
              <Tarjeta className="px-5 py-4">
                <div className="prosa text-[15px] leading-relaxed">
                  <Markdown remarkPlugins={[remarkGfm]}>{t.respuesta}</Markdown>
                </div>
                {!!t.fuentes?.length && (
                  <details className="mt-4 border-t border-line pt-3 text-sm">
                    <summary className="cursor-pointer text-muted hover:text-ink">
                      {t.fuentes.length} {t.fuentes.length === 1 ? 'fuente consultada' : 'fuentes consultadas'}
                    </summary>
                    <ul className="mt-2 space-y-2">
                      {t.fuentes.map((f, j) => (
                        <li key={j}>
                          <Link to={`/documentos/${f.documento_id}`} className="text-ink-strong hover:underline">
                            {entidad(f.entidad)}
                          </Link>
                          {', '}
                          <a
                            href={urlPagina(f.documento_id, f.pagina)}
                            target="_blank"
                            rel="noreferrer"
                            className="text-ink-strong hover:underline"
                            title="Abrir la página"
                          >
                            pág. {f.pagina}
                          </a>
                          <p className="line-clamp-2 text-xs text-muted">{f.extracto}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </Tarjeta>
            ) : t.error ? (
              <Fallo error={t.error} />
            ) : (
              <p className="animate-pulse text-sm text-muted">Buscando en los documentos…</p>
            )}
          </div>
        ))}
      </div>

      {turnos.length === 0 && (
        <div className="mb-6 flex flex-col gap-2">
          {SUGERENCIAS.map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => preguntar(s)}
              className="rounded-md border border-line bg-surface px-4 py-3 text-left text-sm text-ink transition hover:bg-subtle"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="sticky bottom-6 mt-8 flex gap-2 rounded-[10px] border border-line bg-surface p-2"
        onSubmit={(e) => {
          e.preventDefault()
          preguntar(texto)
        }}
      >
        <input
          className={`${campoTexto} border-0`}
          aria-label="Pregunta"
          placeholder="Escribí tu pregunta…"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
        />
        <Boton variante="primario" type="submit" cargando={consultar.isPending} disabled={!texto.trim()} aria-label="Preguntar">
          {!consultar.isPending && <ArrowUp size={16} weight="bold" />}
        </Boton>
      </form>
    </div>
  )
}

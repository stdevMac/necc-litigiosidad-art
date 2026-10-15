import { Container } from '@cloudflare/containers'

interface Env {
  ASSETS: Fetcher
  NECC_API: DurableObjectNamespace<NeccApi>
  GEMINI_API_KEY: string
  CONSULTAS_POR_DIA: string
}

// Backend Python (mvp/Dockerfile) en modo demo. Una sola instancia: la base de la demo es única.
export class NeccApi extends Container<Env> {
  defaultPort = 8000
  sleepAfter = '15m'

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env)
    this.envVars = { GEMINI_API_KEY: env.GEMINI_API_KEY, NECC_DEMO: '1' }
  }

  // El tope vive en el storage del Durable Object: sobrevive a que el contenedor se duerma.
  async consumirConsulta(limite: number): Promise<boolean> {
    const clave = `consultas:${new Date().toISOString().slice(0, 10)}`
    const usadas = (await this.ctx.storage.get<number>(clave)) ?? 0
    if (usadas >= limite) return false
    await this.ctx.storage.put(clave, usadas + 1)
    return true
  }
}

const PREFIJO_POC = '/poc'

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url)
    const ruta = url.pathname

    if (ruta === PREFIJO_POC || ruta === '/presentacion') {
      return Response.redirect(`${url.origin}${ruta}/`, 301)
    }

    if (ruta.startsWith(`${PREFIJO_POC}/api/`)) {
      const api = env.NECC_API.getByName('demo')
      if (request.method === 'POST' && ruta === `${PREFIJO_POC}/api/consulta`) {
        const permitida = await api.consumirConsulta(Number(env.CONSULTAS_POR_DIA))
        if (!permitida) {
          return Response.json(
            { detail: 'Se alcanzó el tope diario de consultas de la demo. Probá de nuevo mañana.' },
            { status: 429 },
          )
        }
      }
      url.pathname = ruta.slice(PREFIJO_POC.length)
      return api.fetch(new Request(url, request))
    }

    // Solo llegan acá las rutas que no son archivos estáticos: las de la SPA van a su index.html.
    if (ruta.startsWith(`${PREFIJO_POC}/`)) {
      return env.ASSETS.fetch(new Request(new URL(`${PREFIJO_POC}/`, url), request))
    }
    return env.ASSETS.fetch(request)
  },
} satisfies ExportedHandler<Env>

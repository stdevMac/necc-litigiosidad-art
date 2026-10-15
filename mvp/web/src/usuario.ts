import { useSyncExternalStore } from 'react'

const CLAVE = 'necc.usuario'
const oyentes = new Set<() => void>()

function suscribir(oyente: () => void) {
  oyentes.add(oyente)
  window.addEventListener('storage', oyente)
  return () => {
    oyentes.delete(oyente)
    window.removeEventListener('storage', oyente)
  }
}

function leer() {
  return localStorage.getItem(CLAVE) ?? ''
}

function guardar(nombre: string) {
  localStorage.setItem(CLAVE, nombre)
  oyentes.forEach((o) => o())
}

/** Nombre de quien revisa: queda registrado en correcciones, aprobaciones y etiquetas. Compartido por toda la app. */
export function useUsuario(): [string, (nombre: string) => void] {
  return [useSyncExternalStore(suscribir, leer), guardar]
}

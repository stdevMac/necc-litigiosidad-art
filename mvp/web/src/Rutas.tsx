import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Documento } from './pages/Documento'
import { Documentos } from './pages/Documentos'

// Gráficos (recharts) y markdown pesan: se cargan solo al entrar a la pantalla que los usa.
const Tablero = lazy(() => import('./pages/Tablero').then((m) => ({ default: m.Tablero })))
const Consulta = lazy(() => import('./pages/Consulta').then((m) => ({ default: m.Consulta })))
const Acciones = lazy(() => import('./pages/Acciones').then((m) => ({ default: m.Acciones })))

export function Rutas() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Documentos />} />
        <Route path="documentos/:id" element={<Documento />} />
        <Route path="tablero" element={<Tablero />} />
        <Route path="consulta" element={<Consulta />} />
        <Route path="acciones" element={<Acciones />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

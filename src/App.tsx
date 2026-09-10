import { Route, Routes } from 'react-router-dom'
import AppLayout from './layouts/AppLayout'
import Simulator from './pages/intelligence/Simulator'
import Performance from './pages/intelligence/Performance'
import LiveTrains from './pages/operations/LiveTrains'
import Network from './pages/operations/Network'
import Stations from './pages/operations/Stations'
import Overview from './pages/Overview'
import Settings from './pages/system/Settings'
import Login from './pages/auth/Login'
import Signup from './pages/auth/Signup'
import { AuthProvider } from './context/AuthContext'
import { PageLoaderProvider } from './context/PageLoaderContext'

function App() {
  return (
    <AuthProvider>
      <PageLoaderProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route element={<AppLayout />}>
            <Route index element={<Overview />} />
            <Route path="operations/live-trains" element={<LiveTrains />} />
            <Route path="operations/stations" element={<Stations />} />
            <Route path="operations/network" element={<Network />} />
            <Route path="intelligence/simulator" element={<Simulator />} />
            <Route path="intelligence/performance" element={<Performance />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </PageLoaderProvider>
    </AuthProvider>
  )
}

export default App

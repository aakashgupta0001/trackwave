import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { usePageLoader } from '../../context/PageLoaderContext'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { signIn, resetPassword } = useAuth()
  const { triggerLoader } = usePageLoader()
  const redirectTo = (location.state as { from?: Location })?.from?.pathname ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(
    searchParams.get('registered') ? 'Registration successful! Please sign in with your credentials.' : null
  )
  const [isResetting, setIsResetting] = useState(false)
  const [resetSent, setResetSent] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMsg(null)
    setSuccessMsg(null)

    if (!email || !password) {
      setErrorMsg('Please enter both your email address and password.')
      return
    }

    setSubmitting(true)
    triggerLoader('Authenticating Operator…', 'Verifying credentials with Supabase Auth', 600)

    try {
      const { error } = await signIn(email, password)
      if (error) {
        setErrorMsg(error.message || 'Failed to sign in. Please check your email and password.')
      } else {
        navigate(redirectTo, { replace: true })
      }
    } catch (err: any) {
      setErrorMsg(err?.message || 'An unexpected error occurred during sign in.')
    } finally {
      setSubmitting(false)
    }
  }

  const handlePasswordReset = async () => {
    if (!email) {
      setErrorMsg('Please enter your email address above to receive a password reset link.')
      return
    }
    setErrorMsg(null)
    setIsResetting(true)
    const { error } = await resetPassword(email)
    setIsResetting(false)
    if (error) {
      setErrorMsg(error.message || 'Could not send password reset email.')
    } else {
      setResetSent(true)
      setSuccessMsg(`Password reset link sent to ${email}. Check your inbox.`)
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950 px-4 py-12 text-slate-100 sm:px-6 lg:px-8">
      {/* Background Decorative Rings */}
      <div className="pointer-events-none fixed inset-0 flex items-center justify-center overflow-hidden opacity-20">
        <div className="h-[600px] w-[600px] rounded-full border border-indigo-500/20 animate-ping" style={{ animationDuration: '6s' }} />
        <div className="absolute h-[800px] w-[800px] rounded-full border border-slate-800" />
      </div>

      <div className="relative w-full max-w-md space-y-8 rounded-2xl border border-slate-800/80 bg-slate-900/60 p-8 shadow-2xl backdrop-blur-xl">
        {/* Header with Logo */}
        <div className="text-center">
          <div className="mx-auto mb-4 flex items-center justify-center">
            <div className="relative flex items-center justify-center">
              <div className="absolute -inset-2 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 via-emerald-500 to-cyan-500 opacity-60 blur-md" />
              <img
                src="/logo.png"
                alt="TrackWave Logo"
                className="relative h-20 w-20 rounded-full border-2 border-indigo-400/80 bg-slate-950 object-cover shadow-xl ring-4 ring-indigo-500/20"
              />
            </div>
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-white">
            TrackWave Portal
          </h2>
          <p className="mt-1.5 text-xs text-slate-400">
            Sign in to access real-time railway telemetry, digital twin & AI predictions
          </p>
        </div>


        {/* Feedback Alerts */}
        {errorMsg && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <div className="font-semibold">Authentication Error</div>
            <div className="mt-0.5">{errorMsg}</div>
          </div>
        )}

        {successMsg && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300">
            <div className="font-semibold">Success</div>
            <div className="mt-0.5">{successMsg}</div>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300">
              Operator Email
            </label>
            <div className="mt-1">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="controller@railway.gov.in"
                className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3.5 py-2 text-sm text-white placeholder-slate-500 shadow-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-slate-300">
                Password
              </label>
              <button
                type="button"
                onClick={handlePasswordReset}
                disabled={isResetting || resetSent}
                className="text-xs text-indigo-400 hover:text-indigo-300 hover:underline"
              >
                {isResetting ? 'Sending…' : resetSent ? 'Link Sent' : 'Forgot password?'}
              </button>
            </div>
            <div className="relative mt-1">
              <input
                type={showPassword ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3.5 py-2 pr-10 text-sm text-white placeholder-slate-500 shadow-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-200"
                tabIndex={-1}
              >
                {showPassword ? (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                  </svg>
                ) : (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs">
            <label className="flex items-center gap-2 text-slate-400 cursor-pointer">
              <input
                type="checkbox"
                defaultChecked
                className="rounded border-slate-800 bg-slate-950 text-indigo-600 focus:ring-indigo-500"
              />
              <span>Remember this terminal</span>
            </label>
            <span className="font-mono text-[11px] text-slate-500">256-BIT SSL</span>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-gradient-to-r from-indigo-600 via-indigo-500 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 cursor-pointer"
          >
            {submitting ? 'Authenticating…' : 'Sign In to Operations'}
          </button>
        </form>

        {/* Footer Navigation */}
        <div className="border-t border-slate-800/80 pt-4 text-center text-xs text-slate-400">
          Don't have an operator account?{' '}
          <Link
            to="/signup"
            className="font-medium text-indigo-400 hover:text-indigo-300 hover:underline"
          >
            Register Operator Account →
          </Link>
        </div>
      </div>
    </div>
  )
}

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { User, Session, AuthError } from '@supabase/supabase-js'
import { supabase, isSupabaseConfigured } from '../lib/supabase'

export type AuthContextType = {
  user: User | null
  session: Session | null
  loading: boolean
  isConfigured: boolean
  signIn: (email: string, password: string) => Promise<{ error: AuthError | Error | null }>
  signUp: (email: string, password: string, fullName?: string) => Promise<{ error: AuthError | Error | null; data?: any }>
  signOut: () => Promise<{ error: AuthError | Error | null }>
  resetPassword: (email: string) => Promise<{ error: AuthError | Error | null }>
  demoLogin: (role?: string) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // If Supabase is configured, initialize real session
    if (isSupabaseConfigured) {
      supabase.auth.getSession().then(({ data: { session } }) => {
        setSession(session)
        setUser(session?.user ?? null)
        setLoading(false)
      })

      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange((_event, session) => {
        setSession(session)
        setUser(session?.user ?? null)
        setLoading(false)
      })

      return () => {
        subscription.unsubscribe()
      }
    } else {
      // Check for demo user in local storage
      const savedDemo = localStorage.getItem('trackwave_demo_user')
      if (savedDemo) {
        try {
          const parsed = JSON.parse(savedDemo)
          setUser(parsed)
        } catch {
          // ignore parse error
        }
      }
      setLoading(false)
    }
  }, [])

  const signIn = async (email: string, password: string) => {
    if (!isSupabaseConfigured) {
      return {
        error: new Error(
          'Supabase is not yet configured. Please set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your .env file or use Demo Mode.'
        ),
      }
    }
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    return { error }
  }

  const signUp = async (email: string, password: string, fullName?: string) => {
    if (!isSupabaseConfigured) {
      return {
        error: new Error(
          'Supabase is not yet configured. Please set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your .env file or use Demo Mode.'
        ),
      }
    }
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: fullName,
          role: 'operator',
        },
      },
    })
    return { data, error }
  }

  const signOut = async () => {
    if (isSupabaseConfigured) {
      const { error } = await supabase.auth.signOut()
      return { error }
    } else {
      localStorage.removeItem('trackwave_demo_user')
      setUser(null)
      setSession(null)
      return { error: null }
    }
  }

  const resetPassword = async (email: string) => {
    if (!isSupabaseConfigured) {
      return {
        error: new Error(
          'Supabase is not yet configured. Please set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your .env file.'
        ),
      }
    }
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/login?reset=true`,
    })
    return { error }
  }

  const demoLogin = (role = 'Senior Operations Controller') => {
    const demoUser = {
      id: 'demo-operator-01',
      email: 'operator@trackwave.internal',
      user_metadata: {
        full_name: 'Railway Operations Controller',
        role,
      },
      app_metadata: {},
      aud: 'authenticated',
      created_at: new Date().toISOString(),
    } as unknown as User

    setUser(demoUser)
    localStorage.setItem('trackwave_demo_user', JSON.stringify(demoUser))
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        loading,
        isConfigured: isSupabaseConfigured,
        signIn,
        signUp,
        signOut,
        resetPassword,
        demoLogin,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

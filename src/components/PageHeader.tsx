type PageHeaderProps = {
  title: string
  description?: string
}

export default function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold text-white">{title}</h1>
      {description && (
        <p className="mt-1 text-sm text-slate-400">{description}</p>
      )}
    </div>
  )
}

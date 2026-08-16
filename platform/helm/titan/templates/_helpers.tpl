{{- define "titan.fullname" -}}
{{- printf "%s-titan" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "titan.labels" -}}
app.kubernetes.io/name: titan
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}


{{/*
Copyright (c) 2026 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License, Version 2.0 which is available at
https://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "dataspace-mgm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name (max 63 characters, DNS naming spec).
*/}}
{{- define "dataspace-mgm.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "dataspace-mgm.backend.fullname" -}}
{{- printf "%s-backend" (include "dataspace-mgm.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dataspace-mgm.frontend.fullname" -}}
{{- printf "%s-frontend" (include "dataspace-mgm.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "dataspace-mgm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "dataspace-mgm.labels" -}}
helm.sh/chart: {{ include "dataspace-mgm.chart" . }}
app.kubernetes.io/part-of: {{ include "dataspace-mgm.name" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels of a component. Call with (dict "ctx" $ "component" "backend").
*/}}
{{- define "dataspace-mgm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "dataspace-mgm.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Name of the service account
*/}}
{{- define "dataspace-mgm.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "dataspace-mgm.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Address of an ingress: scheme and first host. Call with the ingress values.
*/}}
{{- define "dataspace-mgm.ingressUrl" -}}
{{- $host := (first .hosts).host }}
{{- if .tls }}
{{- printf "https://%s" $host }}
{{- else }}
{{- printf "http://%s" $host }}
{{- end }}
{{- end }}

{{/*
Public base address of the backend (BASE_URL).
*/}}
{{- define "dataspace-mgm.backend.baseUrl" -}}
{{- if .Values.backend.baseUrl }}
{{- .Values.backend.baseUrl | trimSuffix "/" }}
{{- else if .Values.backend.ingress.enabled }}
{{- include "dataspace-mgm.ingressUrl" .Values.backend.ingress }}
{{- else }}
{{- printf "http://%s:%d" (include "dataspace-mgm.backend.fullname" .) (int .Values.backend.service.port) }}
{{- end }}
{{- end }}

{{/*
Address of the backend API as seen by the browser (config.json of the UI).
*/}}
{{- define "dataspace-mgm.frontend.apiBaseUrl" -}}
{{- if .Values.frontend.config.apiBaseUrl }}
{{- .Values.frontend.config.apiBaseUrl | trimSuffix "/" }}
{{- else if .Values.backend.ingress.enabled }}
{{- include "dataspace-mgm.ingressUrl" .Values.backend.ingress }}
{{- else }}
{{- printf "http://localhost:%d" (int .Values.backend.service.port) }}
{{- end }}
{{- end }}

{{/*
Name of the secret with SERVICE_CLIENT_SECRET, empty if there is none.
*/}}
{{- define "dataspace-mgm.backend.secretName" -}}
{{- if .Values.backend.secret.existingSecret }}
{{- .Values.backend.secret.existingSecret }}
{{- else if .Values.backend.secret.serviceClientSecret }}
{{- include "dataspace-mgm.backend.fullname" . }}
{{- end }}
{{- end }}

{{/*
Image of a component. Call with (dict "image" .Values.backend.image "ctx" $).
*/}}
{{- define "dataspace-mgm.image" -}}
{{- printf "%s:%s" .image.repository (default .ctx.Chart.AppVersion .image.tag) }}
{{- end }}

{{/*
Secret with the API key of the backend (ADR-0002): the existing secret, or the one the chart creates from
backend.authorization.apiKey.value, or empty.
*/}}
{{- define "dataspace-mgm.backend.apiKeySecret" -}}
{{- with .Values.backend.authorization.apiKey -}}
{{- if .existingSecret -}}
{{- .existingSecret -}}
{{- else if .value -}}
{{- printf "%s-api-key" (include "dataspace-mgm.backend.fullname" $) -}}
{{- end -}}
{{- end -}}
{{- end }}

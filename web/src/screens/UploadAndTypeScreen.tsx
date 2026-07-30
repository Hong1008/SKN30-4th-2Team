import { createClientId } from '../utils/clientId'
import { useEffect, useState, useRef } from "react"

import {
  UploadCloud,
  CheckCircle2,
  X,
  ChevronRight,
  AlertCircle,
  Loader2,
} from "lucide-react"

import { api } from "../api/api"

import { SESSION_ID_KEY, REVIEW_ID_KEY } from "../config"

import { useMetadata } from "../contexts/MetadataContext"

import { useToast } from "../contexts/ToastContext"

import type { SelectionSource } from "../types"

import { getErrorMessage, getNextAction, getUploadErrorMessage } from "../utils/apiErrors"

interface Props {
  sessionId: string | null

  setSessionId: (id: string | null) => void

  setReviewId: (id: string | null) => void

  onNext: (reviewId: string) => void

  onOutOfScope: () => void

  setSessionExpiresAt: (expiresAt: string | null) => void
}

type UploadState = "idle" | "uploading" | "success"

export default function UploadAndTypeScreen({
  sessionId,
  setSessionId,
  setReviewId,
  onNext,
  onOutOfScope,
  setSessionExpiresAt,
}: Props) {
  const { metadata } = useMetadata()

  const { showToast } = useToast()

  const formats =
    metadata?.file_policy.extensions.map((e) => e.toUpperCase()) || []

  const maxSizeBytes = metadata?.file_policy.max_size_bytes ?? 0

  const contractTypes =
    metadata?.contract_types.filter((t) => t.enabled_for_mvp) || []

  const [uploadState, setUploadState] = useState<UploadState>("idle")

  const [isDragging, setIsDragging] = useState(false)

  const [fileName, setFileName] = useState("")

  const [fileSizeStr, setFileSizeStr] = useState("")

  const fileRef = useRef<HTMLInputElement>(null)

  const startRequestKey = useRef<string | null>(null)
  const startLockedRef = useRef(false)

  const uploadLockedRef = useRef(false)

  const uploadControllerRef = useRef<AbortController | null>(null)

  const [pendingFile, setPendingFile] = useState<File | null>(null)

  const [canRetryUpload, setCanRetryUpload] = useState(false)

  const [selectedType, setSelectedType] = useState("")

  const [suggestedType, setSuggestedType] = useState<string | null>(null)

  const [candidateTypes, setCandidateTypes] = useState<string[]>([])

  const [errorMsg, setErrorMsg] = useState("")

  const [emptyDocError, setEmptyDocError] = useState(false)
  const [isStartingReview, setIsStartingReview] = useState(false)
  const [isRemovingFile, setIsRemovingFile] = useState(false)
  const [privacyNoticeConfirmed, setPrivacyNoticeConfirmed] = useState(false)

  useEffect(() => () => uploadControllerRef.current?.abort(), [])

  useEffect(() => {
    if (!sessionId || uploadState !== "idle") return

    const controller = new AbortController()

    api
      .getSession(sessionId, controller.signal)

      .then(({ data }) => {
        if (!data.upload) return

        setFileName(data.upload.file_name)

        setFileSizeStr(`${(data.upload.size_bytes / 1024).toFixed(1)} KB`)

        setSelectedType(data.selected_contract_type || "")

        setSuggestedType(data.suggested_contract_type)

        setCandidateTypes(
          data.candidates.map((candidate) => candidate.contract_type),
        )

        setSessionExpiresAt(data.expires_at)

        setPrivacyNoticeConfirmed(false)
        setUploadState("success")
      })

      .catch((error) => {
        if (error?.name === "AbortError") return

        if (error?.status === 404 || error?.status === 410) {
          setSessionId(null)

          localStorage.removeItem(SESSION_ID_KEY)
        } else {
          setErrorMsg(
            getErrorMessage(error, "이전 검토 세션을 불러오지 못했습니다."),
          )
        }
      })

    return () => controller.abort()
  }, [sessionId, uploadState, onOutOfScope, setSessionExpiresAt, setSessionId])

  const cancelUpload = () => {
    uploadControllerRef.current?.abort()
    uploadControllerRef.current = null
    uploadLockedRef.current = false
    setUploadState("idle")
    setPendingFile(null)
    setCanRetryUpload(false)
    setErrorMsg("")
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]

    e.target.value = ""

    if (!file) return

    processFile(file)
  }

  const processFile = async (file: File) => {
    if (uploadLockedRef.current) return
    setErrorMsg("")
    setEmptyDocError(false)
    setCanRetryUpload(false)
    if (file.size > maxSizeBytes) {
      setErrorMsg(
        `파일 크기가 제한(${(maxSizeBytes / 1024 / 1024).toFixed(1)}MB)을 초과합니다. (현재: ${(file.size / 1024 / 1024).toFixed(1)}MB)`,
      )
      return
    }

    const extension = file.name.split(".").pop()?.toUpperCase() || ""
    if (!formats.includes(extension)) {
      setErrorMsg(
        `지원하지 않는 파일 형식입니다. (.${extension.toLowerCase()})`,
      )
      return
    }

    setFileName(file.name)
    setFileSizeStr((file.size / 1024).toFixed(1) + " KB")
    setPendingFile(file)
    setUploadState("uploading")
    uploadLockedRef.current = true
    const controller = new AbortController()
    uploadControllerRef.current = controller

    try {
      const response = await api.uploadContract(file, controller.signal)

      if (
        response.data.can_start_review === false &&
        response.data.allowed_actions?.includes("REUPLOAD")
      ) {
        setUploadState("idle")
        setEmptyDocError(true)
        setPendingFile(null)
        return
      }

      setUploadState("success")
      setPrivacyNoticeConfirmed(false)
      setPendingFile(null)
      setSelectedType("")
      setSuggestedType(response.data.suggested_contract_type)
      setCandidateTypes(
        response.data.candidates.map((candidate) => candidate.contract_type),
      )
      setSessionExpiresAt(response.data.expires_at)

      const newSessionId = response.data.session_id
      setSessionId(newSessionId)
      localStorage.setItem(SESSION_ID_KEY, newSessionId)
      showToast("파일 업로드가 완료되었습니다.", "success")
    } catch (err: any) {
      if (err?.name === "AbortError") return
      setUploadState("idle")
      const status = err?.response?.status || err?.status
      const isTransient =
        status === 429 || status === 503 || status === 504 || status == null
      setCanRetryUpload(isTransient)

      if (status === 404 || status === 410) {
        showToast("유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.", "error")
        reset()
      } else {
        const message = getUploadErrorMessage(err, maxSizeBytes / 1024 / 1024)
        setErrorMsg(status === 429 && err?.retryAfterSeconds != null
          ? `${message} ${err.retryAfterSeconds}초 후 다시 시도해 주세요.`
          : message)
      }
    } finally {
      uploadLockedRef.current = false
      if (uploadControllerRef.current === controller)
        uploadControllerRef.current = null
    }
  }
  const handleNext = async () => {
    if (!sessionId || !privacyNoticeConfirmed || startLockedRef.current) return
    startLockedRef.current = true
    setIsStartingReview(true)

    try {
      // 1. Confirm contract type

      const selectionSource: SelectionSource =
        selectedType === suggestedType
          ? "SUGGESTED"
          : candidateTypes.includes(selectedType)
            ? "CANDIDATE"
            : "MANUAL"

      const scopeRes = await api.selectContractType(
        sessionId,
        selectedType,
        selectionSource,
      )

      setSessionExpiresAt(scopeRes.data.expires_at)

      // [3] 범위 외 확인(OUT_OF_SCOPE_CONFIRMATION_REQUIRED) 처리

      if (scopeRes.data.review_state === "OUT_OF_SCOPE_CONFIRMATION_REQUIRED") {
        onOutOfScope()

        return
      }

      if (
        !scopeRes.data.can_start_review &&
        !scopeRes.data.allowed_actions?.includes("START_REVIEW")
      ) {
        setErrorMsg("현재 계약 유형으로 검토를 시작할 수 없습니다.")

        return
      }

      // 2. Start review (with Idempotency-Key)

      const idempotencyKey = startRequestKey.current ?? createClientId()

      startRequestKey.current = idempotencyKey

      const reviewRes = await api.startReview(sessionId, idempotencyKey)

      startRequestKey.current = null

      setReviewId(reviewRes.data.review_id)

      localStorage.setItem(REVIEW_ID_KEY, reviewRes.data.review_id)

      // 3. Move to processing screen

      onNext(reviewRes.data.review_id)
    } catch (err: any) {
      const status = err?.status

      const nextAction = getNextAction(err)

      const existingReviewId = err?.details?.review_id

      if (status === 409 && existingReviewId) {
        startRequestKey.current = null

        setReviewId(existingReviewId)

        localStorage.setItem(REVIEW_ID_KEY, existingReviewId)

        onNext(existingReviewId)
      } else if (status === 409) {
        setErrorMsg(
          getErrorMessage(
            err,
            "동일 요청이 이미 처리 중입니다. 잠시 후 다시 확인해 주세요.",
          ),
        )
      } else if (status === 404 || status === 410) {
        showToast(
          "유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.",
          "error",
        )

        reset()
      } else if (nextAction === "SELECT_CONTRACT_TYPE") {
        setErrorMsg(getErrorMessage(err, "계약 유형을 다시 선택해 주세요."))
      } else if (nextAction === "CONFIRM_OUT_OF_SCOPE") {
        onOutOfScope()
      } else if (nextAction === "START_NEW_REVIEW") {
        reset()
      } else {
        setErrorMsg("검토 시작 요청에 실패했습니다.")
      }
    } finally {
      startLockedRef.current = false
      setIsStartingReview(false)
    }
  }

  const removeUploadedFile = async () => {
    if (!sessionId || isRemovingFile || isStartingReview) return
    setIsRemovingFile(true)
    setErrorMsg("")
    try {
      await api.deleteSession(sessionId)
      reset()
      showToast("업로드한 파일을 삭제했습니다.", "success")
    } catch (error: any) {
      setErrorMsg(
        getErrorMessage(error, "파일을 삭제하지 못했습니다. 다시 시도해 주세요."),
      )
    } finally {
      setIsRemovingFile(false)
    }
  }
  const reset = () => {
    uploadControllerRef.current?.abort()

    uploadControllerRef.current = null

    uploadLockedRef.current = false

    setUploadState("idle")

    setErrorMsg("")

    setEmptyDocError(false)

    setPendingFile(null)

    setCanRetryUpload(false)

    setSessionId(null)

    setReviewId(null)

    setSessionExpiresAt(null)

    startRequestKey.current = null
    startLockedRef.current = false
    setIsStartingReview(false)
    setPrivacyNoticeConfirmed(false)

    localStorage.removeItem(SESSION_ID_KEY)

    localStorage.removeItem(REVIEW_ID_KEY)

    if (fileRef.current) fileRef.current.value = ""
  }

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-8 pb-24">
      {/* ── 1. Upload & Type Section ── */}
      <section
        className="
        space-y-7 rounded-2xl border border-slate-200/80 bg-white
        p-6 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:p-8
      "
      >
        <div className="mb-7">
          <h1
            className="
            text-xl font-semibold leading-tight
            tracking-[-0.02em] text-slate-950 sm:text-2xl
          "
          >
            검토할 계약서를 업로드해 주세요
          </h1>

          <p className="mt-2 max-w-2xl break-keep text-sm leading-6 text-slate-500">
            업로드한 문서는 계약서 검토 목적으로만 처리됩니다.
          </p>
        </div>

        {errorMsg && (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3.5 text-sm font-medium text-rose-700 animate-fade-up">
            <div className="flex items-center gap-3">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <p>{errorMsg}</p>
            </div>
            {canRetryUpload && pendingFile && (
              <button
                type="button"
                onClick={() => processFile(pendingFile)}
                className="shrink-0 rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-100"
              >
                같은 파일 다시 시도
              </button>
            )}
          </div>
        )}

        {emptyDocError && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-5 animate-fade-up">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-amber-900 mb-1">
                  검토 가능한 조항이 없습니다
                </h4>
                <p className="text-xs text-amber-700/90 break-keep">
                  파일 검증은 통과했으나, 문서 내에서 비교 가능한 표준 계약
                  조항을 추출하지 못했습니다. 글자가 포함된 정상적인 계약서인지
                  확인 후 다시 업로드해 주세요.
                </p>
              </div>
            </div>
            <button
              onClick={() => fileRef.current?.click()}
              className="shrink-0 inline-flex items-center justify-center rounded-xl bg-amber-600 px-4 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-amber-700 transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-amber-500/20"
            >
              새 문서 업로드
            </button>
          </div>
        )}

        {uploadState === "idle" && (
          <div
            role="button"
            tabIndex={0}
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault()

              setIsDragging(false)

              const file = e.dataTransfer.files?.[0]

              if (file) processFile(file)
            }}
            onClick={() => {
              fileRef.current?.click()
            }}
            className={`group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border-2 border-dashed px-6 py-6 text-center transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
              isDragging
                ? "scale-[1.01] border-blue-500 bg-blue-50 shadow-lg shadow-blue-500/10"
                : "border-slate-300 bg-slate-50/60 hover:border-blue-400 hover:bg-blue-50/50"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept={formats.map((f) => `.${f.toLowerCase()}`).join(",")}
              onChange={handleFileChange}
            />

            <div className="flex w-full flex-col items-center justify-center px-4 py-6">
              <div
                className={`mb-3 flex size-12 items-center justify-center rounded-xl transition-all duration-200 group-hover:-translate-y-0.5 ${
                  isDragging
                    ? "bg-blue-600 text-white shadow-lg shadow-blue-600/25"
                    : "bg-white text-blue-600 shadow-sm ring-1 ring-slate-200"
                }`}
              >
                <UploadCloud
                  className={`size-6 transition-colors ${
                    isDragging ? "text-white" : "text-blue-600"
                  }`}
                />
              </div>
              <p className="mb-2 text-[15px] font-semibold leading-6 tracking-[-0.01em] text-slate-900">
                파일을 이곳에 드래그하거나 직접 선택하세요
              </p>

              <p className="mb-4 text-xs font-medium tracking-[0.08em] text-slate-500">
                {formats.join(" · ")}
              </p>

              <button
                onClick={(e) => {
                  e.stopPropagation()
                  fileRef.current?.click()
                }}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-xs font-semibold text-slate-700 transition-colors duration-150 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15"
              >
                파일 선택
              </button>
            </div>

            <div className="absolute bottom-5 left-0 right-0 text-center">
              <p className="text-xs text-slate-500 font-medium">
                최대 {(maxSizeBytes / 1024 / 1024).toFixed(1)}MB까지 업로드
                가능합니다
              </p>
            </div>
          </div>
        )}

        {/* Uploading */}
        {uploadState === "uploading" && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center shrink-0">
                <Loader2 className="w-5 h-5 animate-spin text-blue-600" aria-hidden="true" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-slate-950 truncate pr-4">
                    {fileName}
                  </p>
                  <span className="text-xs text-slate-600 shrink-0">
                    {fileSizeStr}
                  </span>
                </div>
                <div className="flex items-center gap-3 mb-1.5">
                  <div className="flex-1 h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full w-full animate-pulse rounded-full bg-gradient-to-r from-blue-600 to-cyan-500" />
                  </div>
                  <span className="text-xs font-medium text-slate-600 shrink-0">
                    파일 업로드 중
                  </span>
                  <button
                    type="button"
                    onClick={cancelUpload}
                    className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    업로드 취소
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Success */}
        {uploadState === "success" && (
          <div className="space-y-4">
          <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-emerald-500">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-950 truncate">
                  {fileName}
                </p>
                <p className="text-xs text-slate-600 mt-0.5">
                  {fileSizeStr} · 업로드 완료
                </p>
              </div>
              <button
                onClick={() => void removeUploadedFile()}
                disabled={isStartingReview || isRemovingFile}
                aria-label={isRemovingFile ? "파일 제거 중" : "파일 제거"}
                className="text-slate-400 hover:text-rose-500 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5" aria-labelledby="privacy-notice-title">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 size-5 shrink-0 text-blue-500" aria-hidden="true" />
              <div className="min-w-0">
                <h2 id="privacy-notice-title" className="text-sm font-bold text-slate-900">개인정보 포함 여부를 확인해 주세요</h2>
                <p id="privacy-notice-description" className="mt-2 max-w-2xl break-keep text-xs leading-5 text-slate-600">
                  개인정보는 자동으로 가려지지 않습니다. 검토에 불필요한 주민등록번호, 계좌번호, 연락처, 주소 등은 업로드 전에 삭제하거나 가려 주세요. 업로드 문서는 처리 완료 또는 세션 만료 후 삭제됩니다.
                </p>
                <label className={`mt-4 flex items-start gap-2.5 rounded-xl border p-3 text-xs leading-5 text-slate-700 transition-colors ${privacyNoticeConfirmed ? 'border-blue-200 bg-blue-50/50' : 'border-slate-200 bg-white/80'} ${isStartingReview ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:border-blue-200 hover:bg-white'}`}>
                  <input
                    type="checkbox"
                    checked={privacyNoticeConfirmed}
                    disabled={isStartingReview || isRemovingFile}
                    onChange={(event) => setPrivacyNoticeConfirmed(event.target.checked)}
                    aria-describedby="privacy-notice-description"
                    className="mt-0.5 size-4 shrink-0 accent-blue-600"
                  />
                  <span>문서에 불필요한 개인정보가 없는지 확인했으며, 개인정보가 자동으로 마스킹되지 않는다는 안내를 확인했습니다.</span>
                </label>
              </div>
            </div>
          </div>
          </div>
        )}
        {/* ── 2. Contract Type Section ── */}
        <div className="space-y-4 border-t border-slate-100 pt-6">
          <div className="grid md:grid-cols-3 gap-3">
            {contractTypes.map((type) => {
              const active = selectedType === type.code

              return (
                <button
                  key={type.code}
                  disabled={uploadState === "uploading" || isStartingReview}
                  onClick={() => {
                    setSelectedType(type.code)

                    startRequestKey.current = null
                  }}
                  aria-pressed={active}
                  className={`relative min-h-20 rounded-xl border px-4 py-3.5 text-left transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
                    active
                      ? "border-blue-500 bg-blue-50/30 shadow-sm ring-2 ring-blue-500/10"
                      : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-sm"
                  }`}
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <h3
                      className={`text-sm font-semibold ${
                        active ? "text-blue-700" : "text-slate-900"
                      }`}
                    >
                      {type.label}
                    </h3>
                    {active && (
                      <CheckCircle2 className="w-5 h-5 text-blue-600" />
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                    {type.description}
                  </p>
                </button>
              )
            })}
          </div>

          <div className="rounded-xl bg-slate-50/70 px-5 py-4">
            <p className="text-xs text-slate-600 leading-relaxed flex-1">
              현재 지원 범위:{" "}
              {contractTypes.map((type) => type.label).join(", ")}
              <br />
              선택한 계약 유형과 문서 내용이 일치하지 않는 경우, 검토 전에 확인
              안내가 표시됩니다.
            </p>
          </div>
          <div className="flex justify-end">
            <p className="text-xs text-slate-500 italic">
              * 그 외의 계약서 지원 서비스는 추후 확장 예정입니다.
            </p>
          </div>
        </div>
      </section>

      {/* ── 3. Bottom Controls & Help ── */}
      <div className="sticky bottom-4 z-20 flex flex-col-reverse gap-3 rounded-2xl border border-slate-200/80 bg-white/95 p-3 shadow-[0_8px_24px_rgba(15,23,42,0.07)] backdrop-blur-xl sm:flex-row sm:items-center sm:justify-end">
        <button
          onClick={handleNext}
          disabled={uploadState !== "success" || !selectedType || !privacyNoticeConfirmed || isStartingReview}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition-[background-color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20 ${
            uploadState === "success" && selectedType && privacyNoticeConfirmed && !isStartingReview
              ? "bg-blue-600 text-white shadow-[0_1px_2px_rgba(37,99,235,0.2),0_6px_16px_rgba(37,99,235,0.16)] hover:-translate-y-px hover:bg-blue-700 hover:shadow-md active:translate-y-0 active:bg-blue-800"
              : "cursor-not-allowed bg-slate-200 text-slate-500"
          }`}
        >
          {isStartingReview ? '검토 시작 요청 중' : '선택한 유형으로 검토 시작'}
          {isStartingReview ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <ChevronRight className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}

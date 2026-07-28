export type Screen =
  | 'upload-and-type'
  | 'out-of-scope'
  | 'processing'
  | 'results'
  | 'clause-detail'
  | 'chatbot'

export type ResultCode = 'NONE' | 'EXTRA' | 'NO_MATCH' | 'MISSING'

export interface ClauseResult {
  id: string
  article: string
  excerpt: string
  status: ResultCode
  category: string
  summary: string
  toxic_patterns?: {code: string; label: string}[]
  categoryCode?: string
  standardTitle?: string
  standardText?: string
  standardSource?: string
}

export interface MissingClauseResult {
  id: string
  category: string
  title: string
  text: string
  explanation: string
}

// --- API Types based on api-draft.md ---

export interface ApiResponse<T> {
  data: T;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface ApiError {
  code: string;
  message: string;
  field?: string | null;
  retryable?: boolean;
  next_action?: string;
  details?: unknown;
}

export interface ReviewSessionData {
  session_id: string;
  review_state: string;
  upload?: {
    file_name: string;
    size_bytes: number;
    extension: string;
  };
  scope_status: string;
  scope_message: string;
  suggested_contract_type: string | null;
  selected_contract_type: string | null;
  selection_source: string | null;
  candidates: any[];
  matched_clause_count: number;
  allowed_actions: string[];
  expires_at: string;
  can_start_review?: boolean;
}

export interface ReviewProgress {
  sequence: number;
  stage: string;
  current: number;
  total: number;
  percent: number;
  message?: string | null;
}

export interface ReviewData {
  review_id: string;
  review_state: string;
  mcp_review_status: string | null;
  snapshot?: unknown;
  progress?: ReviewProgress | null;
  error?: ApiError | null;
  started_at?: string;
  completed_at?: string;
  expires_at?: string;
  links?: Record<string, string>;
}

export interface ResultsData {
  review: {
    review_id: string;
    review_state: string;
    mcp_review_status: string;
    contract_type: string;
    started_at: string;
    completed_at: string;
    expires_at: string;
    disclaimer: string;
  };
  summary: {
    clause_results: {
      total: number;
      NONE: number;
      EXTRA: number;
      NO_MATCH: number;
    };
    missing_standard_clauses: number;
    toxic_pattern_candidates: number;
  };
  clause_results: ClauseResult[];
  missing_standard_clauses: MissingClauseResult[];
}

export interface ContractTypeMeta {
  code: string;
  label: string;
  description?: string | null;
  enabled_for_mvp?: boolean | null;
}

export interface MetaCodeLabel {
  code: string;
  label: string;
}

export interface FilePolicyMeta {
  extensions: string[];
  max_size_bytes: number;
  single_file_only: boolean;
  encrypted_file_allowed: boolean;
}

export interface MetadataData {
  schema_version: string;
  updated_at: string;
  contract_types: ContractTypeMeta[];
  categories: MetaCodeLabel[];
  result_codes: string[];
  result_code_details: MetaCodeLabel[];
  progress_stages: string[];
  progress_stage_details: MetaCodeLabel[];
  file_policy: FilePolicyMeta;
}

export interface GroundingData {
  items: Array<{
    source?: string;
    title?: string;
    text?: string;
    url?: string;
  }>;
}

export interface ChatSource {
  source_type?: 'clause' | 'law' | string;
  label?: string;
  title?: string;
  source_id?: string;
}

export interface ChatResponse {
  answer: string | null;
  sources: ChatSource[];
  refused: boolean;
  limitations: string[];
  disclaimer: string;
}

export interface RequiredConfirmation {
  field?: string;
  message?: string;
}

export interface SuggestionResponse {
  outcome: string;
  text: string | null;
  purpose: string | null;
  key_changes: string[];
  required_confirmations: RequiredConfirmation[];
  missing_inputs: string[];
  disclaimer: string;
}

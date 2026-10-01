import type { ApiError } from "../api/client";
import type { ErrorCode } from "../api/types";

/** One plain message per error code (P13.5), worded from SRS 16's "what the user sees". A
 * `Record` over the generated `ErrorCode` union, so a new code the API adds fails the type check
 * until it has a message here (a test checks the same against the OpenAPI document).
 *
 * A function receives the error: some messages name what the server told us (the Agent holding
 * a lease, the field that failed validation). */
type Message = string | ((error: ApiError) => string);

const serverMessage = (error: ApiError) => error.message;

function details(error: ApiError): Record<string, unknown> {
  return typeof error.details === "object" && error.details !== null
    ? (error.details as Record<string, unknown>)
    : {};
}

export const MESSAGES: Record<ErrorCode, Message> = {
  // Tally and the Agent's machine (SRS 16)
  TALLY_SERVER_DISABLED:
    "TallyPrime's XML/HTTP server is off. Turn it on in TallyPrime's connectivity settings (default port 9000).",
  TALLY_UNREACHABLE:
    "Tally not running — the Windows user may have logged off. Log in and start TallyPrime; Remote Desktop users should disconnect instead of logging off.",
  TDL_NOT_LOADED:
    "Configuration error: the Tally Analytics TDL is not loaded in TallyPrime. Load the TDL files and try again.",
  COMPANY_NOT_LOADED:
    "The company is not open in TallyPrime. Open it in Tally, or update its name in the Agent's Tally settings.",
  COMPANY_MISMATCH:
    "The company open in Tally is not the one this Agent was registered for. Re-register the Agent.",
  TALLY_EXPORT_TIMEOUT:
    "Tally took too long to answer, so part of the sync was skipped. Lower the Agent's batch size.",
  QUEUE_FULL:
    "The Agent's local queue is full, so it has stopped pulling from Tally. Restore its internet connection.",
  SYNC_LOCKED: (error) => {
    const holder = details(error).holder;
    return typeof holder === "string" && holder
      ? `Sync in progress by ${holder}. It will continue once that finishes.`
      : "Another sync is in progress. It will continue once that finishes.";
  },
  STALE_ALTERID: "A record older than the stored copy was ignored. Nothing needs to be done.",
  CREDENTIAL_INVALID:
    "The Agent's credential is not valid. Rotate the credential and enter the new one in the Agent.",
  AGENT_REVOKED: "This Agent has been revoked. Register a new Agent on that computer.",
  AGENT_INCOMPATIBLE:
    "Agent update required: this Agent or its TDL is older than the server needs.",
  AGENT_SELECTION_REQUIRED: "This company has more than one Agent. Choose which one should sync.",
  AGENT_LOST:
    "The Agent stopped responding while it was syncing, so the command failed. Restart the Agent and sync again.",
  UDF_NOT_FOUND:
    "A mapped custom field was not in Tally's export; it was stored as empty. Check the mapping or the Tally customisation.",
  // Data from Tally (listed in Data Quality)
  UNRESOLVED_GROUP:
    "A group's parent chain could not be resolved, so its ledgers are left out of classified figures. See Data Quality.",
  UNSUPPORTED_ALLOCATION_TYPE:
    "A bill allocation has a type that is not recognised, so it is left out of aging. See Data Quality.",
  UNLINKED_CREDIT_NOTE:
    "A credit note is not linked to an original bill, so it is listed under Unclassified Adjustments.",
  UNLINKED_DEBIT_NOTE:
    "A debit note is not linked to an original bill, so it is listed under Unclassified Adjustments.",
  DEBIT_CREDIT_IMBALANCE:
    "A voucher's debits and credits do not match, so it was not stored. See Data Quality.",
  UNKNOWN_MASTER_REFERENCE:
    "A voucher names a ledger, item or voucher type that has not been synced yet. It is retried on the next sync.",
  PARSE_ERROR:
    "Part of Tally's answer could not be read; the rest was stored. See the sync errors.",
  CHUNK_FAILED: "Part of an upload could not be stored. It is retried on the next sync.",
  KEY_LIST_SUSPICIOUS:
    "A deletion check would have marked too many records as deleted at once, so nothing was changed. Review it in Data Quality.",
  GATE_NOT_PASSED:
    "This needs a Tally check that has not passed yet, so the full-sync-only path is used.",
  // Commands and requests
  INVALID_COMMAND_STATE: "That sync has already finished or is no longer running.",
  VALIDATION_ERROR: serverMessage, // the server names the field and the rule
  CONFLICT: serverMessage, // the server says what conflicts
  NOT_AUTHENTICATED: "Your session has ended. Please sign in again.",
  FORBIDDEN: "Your role in this company does not allow this.",
  NOT_FOUND: "That was not found. It may have been removed.",
  RATE_LIMITED: "Too many requests. Please wait a moment and try again.",
  HTTPS_REQUIRED: "This service only works over a secure (https) connection.",
};

/** The message for an error from the API; a network failure has its own. */
export function messageFor(error: ApiError): string {
  if (error.code === "NETWORK_ERROR") {
    return "The server could not be reached. Check your internet connection and try again.";
  }
  const message = MESSAGES[error.code];
  return typeof message === "function" ? message(error) : message;
}

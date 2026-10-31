export const SECTIONS = ["Physics", "Chemistry", "Botany", "Zoology"] as const;

export type Pattern = {
  name: string; sections: { name: string; questions: number }[]; total_questions: number; duration_minutes: number;
  marks_correct: number; marks_wrong: number; marks_unanswered: number; verify_note: string; format_note: string;
  exam_time?: string;
};
export type Bank = Record<string, { sample: number; ai_checked: number; reviewed: number }>;
export type Readiness = { unseen: Record<string, number>; full_mocks_available: number; generating: boolean; can_generate: boolean };
export type Chapter = { id: number; code: string; subject: string; class_level: string; name: string; est_hours: number; questions: number };
export type AttemptSummary = { id: number; title: string; mode: string; status: string; score: number | null; max_score: number;
  questions: number; started_at: string; submitted_at: string | null; remaining_seconds: number; booklet_code: string | null };

export type QuestionView = {
  position: number; section: string; stem: string; options: string[]; format: string; chapter?: string; selected_index: number | null;
  marked_for_review: boolean; visited: boolean; review_status: string;
  correct_index?: number; explanation?: string | null; topic?: string | null; difficulty?: string; time_spent_seconds?: number;
  outcome?: "correct" | "wrong" | "skipped";
};
export type SectionStat = { section: string; questions: number; attempted: number; correct: number; wrong: number; score: number;
  max: number; accuracy: number | null; avg_seconds: number };
export type ChapterStat = { chapter_id: number; chapter: string; subject: string; questions: number; attempted: number; correct: number;
  accuracy: number | null };
export type AttemptView = {
  id: number; title: string; mode: string; status: "ready" | "in_progress" | "submitted"; strict_omr: boolean; pattern: Pattern;
  duration_seconds: number; remaining_seconds: number; has_sample_questions: boolean; has_ai_questions: boolean;
  booklet_code: string | null; roll_number: string | null; section_counts: Record<string, number>; questions: QuestionView[];
  result?: { score: number; max_score: number; auto_submitted: boolean; attempted: number; correct: number; wrong: number; skipped: number;
    negative_marks: number; accuracy: number | null; time_used_seconds: number; focus_lost_count: number; sections: SectionStat[];
    chapters: ChapterStat[]; recorded_as_mock_test: boolean; advice: string[] };
};

export const clock = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h ? `${h}:` : ""}${String(m).padStart(h ? 2 : 1, "0")}:${String(sec).padStart(2, "0")}`;
};

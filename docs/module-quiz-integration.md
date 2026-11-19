# Module quizzes: backend reply

Everything in the "Module quizzes — backend handoff" is implemented as written,
with the differences listed at the end. All paths are under `/api/v1/`.

## Authoring (instructor)

| Request | Notes |
| --- | --- |
| `POST /quizzes/` | Accepts `section` (the module title exactly as stored on its lessons). A second quiz on the same course and section returns `400 {"section": ["This module already has a quiz."]}`. Created as a draft. |
| `PATCH /quizzes/<id>/` | Renaming a module: send the new `section`. Moving onto a module that already has a quiz returns the same `400`. |
| `GET /quizzes/?course=<id>` | Only that course's quizzes, still a plain JSON array. A non-numeric `course` returns `400`. |
| `POST /questions/` | Accepts `hint` and `explanation` (both optional). |

Quiz objects now carry `section` and `has_completed_attempts`. Each nested
question carries `hint` and `explanation`.

When `has_completed_attempts` is `true`, creating, editing or deleting that
quiz's questions or options returns:

```json
400 {"detail": "This quiz already has attempts, so its questions are locked."}
```

The quiz settings (title, description, pass mark, attempts, section, published)
stay editable. Publishing still requires a published course, at least one
question, and at least two options per question with exactly one of them correct.

## Playing (student)

| Request | Notes |
| --- | --- |
| `GET /courses/<id>/quizzes/` | Adds `section` and `question_count`. Students see published quizzes only; the course instructor sees drafts too. |
| `GET /student/quizzes/<id>/` | Adds `section`, and `hint` on each question. Never includes `explanation` or `is_correct`. |
| `POST /student/quizzes/<id>/start/` | Unchanged. |
| `POST /student/quiz-attempts/<attempt_id>/answer/` | **New.** Body `{"question": 15, "selected_option": 61}`. |
| `POST /student/quiz-attempts/<attempt_id>/submit/` | Finishes the attempt. |

`answer/` returns `200`:

```json
{"is_correct": false, "correct_option": 60, "explanation": "A newton (N) is the SI unit of force.", "marks_awarded": "0.00"}
```

Its errors are:

| Status | Body | When |
| --- | --- | --- |
| `400` | `{"code": "ALREADY_ANSWERED", "detail": "This question was already answered."}` | A second check of the same question. The first answer is kept. |
| `400` | `{"detail": "Question 15 does not belong to this quiz."}` | The question is from a different quiz. |
| `400` | `{"detail": "Option 61 does not belong to question 15."}` | The option is from a different question. |
| `400` | `{"detail": "This quiz attempt has already been submitted."}` | The attempt is finished. |
| `404` | | The attempt belongs to someone else. |
| `403` | `NOT_ENROLLED` | The student is no longer enrolled. |

Submit rules:

- Checked answers are final. Send `{"answers": []}` or `{}` once every question
  is checked. If you re-send checked questions, their options are ignored.
- Unchecked questions must be in `answers`. If any question is neither checked
  nor sent, the response is still `400` `You must answer every question before submitting the quiz.`
- The response shape is unchanged. Points for a question are awarded only once
  per student, however many attempts it takes.

A quiz never locks a lesson or a module.

## Differences from the handoff

1. The migration is `0060_module_quiz`. Migrations 0057–0059 had already landed.
2. A blank `section` (`""`) is stored as `null`, the same as no module. Other text
   is stored exactly as sent: no trimming and no case folding.
3. The question lock also blocks **adding** questions or options to a locked quiz,
   not only `PATCH`/`DELETE`. An added question would change the scoring for
   later attempts, and an added option could create a second correct answer.
4. In `submit/`, a question from another quiz now returns
   `Question N does not belong to this quiz.` instead of the
   "answer every question" message.

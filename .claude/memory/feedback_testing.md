---
name: Testing conventions
description: All tests must be in tests/ folder, Gherkin-annotated, reusable across sessions
type: feedback
---

All tests — whether written by Claude or Copilot — must be saved in the `tests/` folder so they can be found, rerun, and extended in future sessions.

**Why:** Tests written as throwaway inline scripts (e.g. in a Bash tool call) are lost after the session. Storing them in `tests/` makes them reusable and discoverable.

**How to apply:**
- Never write test logic as inline `python3 -c "..."` scripts when the test is validating a real feature. Write it to `tests/test_<feature>.py` instead.
- Every test function must have a Gherkin-style docstring:
  ```python
  def test_circuit_breaker_trips_on_three_stops():
      """
      Given 3 consecutive stop_loss trades within the last 4 hours
      When is_circuit_open() is called
      Then it returns (True, resume_in_secs > 0)
      """
  ```
- When code behaviour changes (e.g. a signal rule is updated), review existing tests in `tests/` and update any that test the changed behaviour.
- Tests should be runnable standalone: `~/.pyenv/versions/3.11.15/bin/python3 tests/test_<feature>.py`

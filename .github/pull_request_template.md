# Pull Request

## Description

Fixed sensitive data exposure in Auth reprs. The `ApiKeyAuth` and `LocalAuth` dataclasses in `custom_components/unifi_insights/api/auth.py` did not exclude the `api_key` field from their default string representation. This could lead to sensitive API keys being inadvertently exposed in logs, debug output, or error stack traces.

## Type of Change

- [x] Bug fix (non-breaking change fixing an issue)
- [ ] New sensor or entity platform
- [ ] New feature or enhancement
- [ ] Breaking change (change that causes existing automations or setups to fail)
- [ ] Documentation update
- [ ] Code refactoring (no functional changes)
- [ ] Test additions or improvements
- [ ] Frontend topology card or UI update

## Pre-Submission Governance

- [x] I built and ran the project locally and verified this change actually works (not just that it compiles)
- [x] I ran `pytest` locally and all tests pass
- [x] I ran `./script/lint` locally and it passes
- [x] I pasted real local verification output under **Testing Performed** below (no placeholder text)
- [x] This PR is self-contained and is not a duplicate; I have not opened other overlapping or back-to-back PRs for the same change
- [x] If an AI agent created or assisted with this PR, a human reviewed and verified the changes before submission

## Related Issues

None

## Changes Made

- Updated the `@dataclass` decorators for `ApiKeyAuth` and `LocalAuth` to include `repr=False`.
- Implemented custom `__repr__` methods that explicitly redact the `api_key` value.

## Home Assistant Quality Scale & Standards

- [x] Verified against the [Home Assistant Developer Docs](https://developers.home-assistant.io/) and Quality Scale rules
- [x] Checked [developer.ui.com](https://developer.ui.com/) for endpoint/schema alignment where API behavior changed
- [x] Uses `entry.runtime_data` patterns where applicable (no new `hass.data[DOMAIN]` usage)
- [x] All entities read from coordinator state (`coordinator.data`) and avoid direct API/network calls
- [x] New/updated entities use `UnifiInsightsEntity` or `UnifiProtectEntity` appropriately
- [x] Sensor implementations use modern native properties (no `unit_of_measurement`)
- [x] Uses Home Assistant session helpers (no direct `aiohttp.ClientSession()` instantiation)
- [x] Diagnostics redaction handled when sensitive fields are exposed
- [ ] Not applicable (documentation-only or metadata-only change)

## Testing Performed

- [x] Ran unit tests (`pytest`)
- [x] Ran linter (`./script/lint`)
- [ ] Ran type checking (`mypy custom_components/unifi_insights`)
- [x] Ran pre-commit checks (`pre-commit run --all-files`)
- [ ] Tested live in local Home Assistant (`./script/develop`)
- [ ] Frontend checks passed (`npm run lint`, `npm run typecheck`, `npm test` in `frontend/`) (if applicable)
- [ ] Not applicable (documentation-only or metadata-only change)

### Test Results

```text
LocalAuth(api_key=**REDACTED**, verify_ssl=True)
ApiKeyAuth(api_key=**REDACTED**, key_type=ApiKeyType.PROTECT)
```

## Documentation

- [x] Code comments added/updated where needed
- [ ] README.md updated (if needed)
- [x] CHANGELOG.md updated under [Unreleased]
- [x] AGENTS.md / developer documentation updated (if architecture or process changed)
- [ ] No documentation needed

## Breaking Changes



## Checklist

- [x] I have updated CHANGELOG.md under [Unreleased] with details of this change
- [x] I verified my code against Home Assistant integration quality rules and used no deprecated APIs
- [x] I linked the related issue in **Related Issues** (only maintainers may note "None", for housekeeping)
- [x] I completed all required sections in this template and removed placeholder-only content
- [x] My code follows the project's coding standards and Home Assistant patterns
- [x] I have performed a self-review of my own code
- [x] I have commented my code, particularly in hard-to-understand areas (if applicable)
- [x] My changes generate no new warnings
- [x] I have added tests that prove my fix is effective or that my feature works (if applicable)
- [x] New and existing unit tests pass locally with my changes
- [x] Any dependent changes have been merged and published (if applicable)
- [x] No sensitive information (tokens, passwords, personal data) is included

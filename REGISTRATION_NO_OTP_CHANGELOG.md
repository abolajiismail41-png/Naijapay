# Registration without OTP

## Behavior changes
- `POST /api/v1/auth/register` creates a user, creates a server-side session, and returns the normal access/refresh token pair with HTTP 201.
- The React registration page stores those tokens through the existing AuthContext and routes the user to transaction PIN setup.
- Nigerian phone numbers continue to be normalized and validated by the existing Pydantic `Phone` type and frontend `normalizePhone` helper.
- Registration no longer sends an OTP and does not falsely mark the phone as verified.
- Login no longer blocks a user solely because the phone has not been verified.
- Existing accounts cannot be taken over by re-registering the same number; duplicate registration returns HTTP 409 without changing the existing password.
- Optional phone verification remains available through authenticated `POST /api/v1/auth/phone/verification/request`, followed by `POST /api/v1/auth/verify-phone`.
- Password reset can send an OTP to an active account even if its phone was not verified during signup; the reset still requires the valid one-time code.
- Registration is rate-limited independently of OTP requests.
- Bill purchases continue to require the existing short-lived, single-use transaction-PIN step-up token.

## Files changed
- `backend/app/modules/auth/api.py`
- `backend/app/modules/auth/service.py`
- `backend/tests/api/helpers.py`
- `backend/tests/api/test_auth.py`
- `backend/tests/api/test_referrals_promotions.py`
- `frontend/src/pages/auth.tsx`

## Validation
- Python compilation passed for backend application, tests, and migrations.
- Full pytest execution was blocked in this environment because `asyncpg` is not installed. Install the backend requirements and run the test suite against the configured test PostgreSQL/Redis services before deployment.
- Frontend build/tests were not run because frontend dependencies are not installed in this environment.

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from app.utils.session import sync_user_session


router = APIRouter()


@router.get("/admin/stop-impersonation")
async def stop_impersonation_public(request: Request):
    """
    Ruta de ieșire din shadowing trebuie să fie accesibilă și când rolul curent NU e superadmin
    (pentru că ești logat ca alt user). Ne bazăm pe `original_admin_id` din sesiune.
    """
    orig_id = request.session.get("original_admin_id")
    if not orig_id:
        raise HTTPException(status_code=403, detail="Nu există sesiune de shadowing activă.")

    # Revenim la superadmin-ul original și resincronizăm sesiunea complet.
    try:
        del request.session["original_admin_id"]
    except KeyError:
        pass

    await sync_user_session(request, int(orig_id))
    return RedirectResponse(url="/admin/dashboard", status_code=303)


from fastapi import Request, HTTPException, Depends
from starlette import status

# 1. Verifica daca e logat (de baza)
async def login_required(request: Request):
    if not request.session.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Trebuie să fii logat pentru a accesa această resursă."
        )
    return request.session.get("user_id")

# 2. Verifica daca e Superadmin (pentru Panoul Global)
async def superadmin_required(request: Request):
    # Mai întâi verificăm dacă e măcar logat
    await login_required(request)
    
    if request.session.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces interzis. Necesită privilegii de Superadmin."
        )
    return True

# 3. Verifica accesul la Company Admin (Cea mai deșteaptă logică a ta)
async def company_admin_required(request: Request):
    await login_required(request)
    
    role = request.session.get("role")
    company_id = request.session.get("company_id")

    # LOGICA: Trece dacă e Superadmin (care face shadowing) 
    # SAU dacă e Company Admin și are un ID de companie valid
    if role == "superadmin":
        return True
    
    if role == "company_admin" and company_id:
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acces neautorizat. Nu ai o companie activă sau rolul necesar."
    )

async def company_admin_required(request: Request):
    await login_required(request)
    
    role = request.session.get("role")
    company_id = request.session.get("company_id")

    # 1. Superadmin (Shadowing) - trece mereu
    if role == "superadmin":
        return True
    
    # 2. Pending Admin - are voie să intre în router (ca să vadă waiting.html)
    if role == "pending_admin":
        return True

    # 3. Company Admin - trece doar dacă are și firmă asociată (siguranță maximă)
    if role == "company_admin" and company_id:
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acces neautorizat. Contactați administratorul pentru activare."
    )
@echo off
REM ARTMiE Recommender — weekly refresh
REM Schedule via Windows Task Scheduler: Sundays 03:00 Europe/Bratislava
setlocal

set PYTHON="C:\Users\Valerian\AppData\Local\Python\bin\python.exe"
set ROOT=C:\Users\Valerian\Desktop\Claude 1TEST\artmie_recomander
set TS=%date:~10,4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%
set LOG=%ROOT%\logs\weekly_%TS%.log
set PYTHONIOENCODING=utf-8

cd /d "%ROOT%"

echo ==== weekly refresh starting %date% %time% ==== >> "%LOG%"

%PYTHON% scripts\02a_incremental_export.py     >> "%LOG%" 2>&1 || goto :fail
%PYTHON% scripts\02b_refresh_products.py       >> "%LOG%" 2>&1 || goto :fail
REM 03a (seasonal mask) is OBSOLETE — seasonal handling moved into 03b scoring
REM (off-season -> 0.05x multiplier, in-season -> 1.5x boost) per user 2026-04-26
%PYTHON% scripts\03b_compute_bestsellers.py    >> "%LOG%" 2>&1 || goto :fail
%PYTHON% scripts\04_compute_recommendations.py >> "%LOG%" 2>&1 || goto :fail
%PYTHON% scripts\05_compute_alternatives.py    >> "%LOG%" 2>&1 || goto :fail
%PYTHON% scripts\06_curate_homepage.py         >> "%LOG%" 2>&1 || goto :fail
REM Parent collection sync across all 4 stores
%PYTHON% scripts\07_sync_parent_collections.py --store sk >> "%LOG%" 2>&1
%PYTHON% scripts\07_sync_parent_collections.py --store pl >> "%LOG%" 2>&1
%PYTHON% scripts\07_sync_parent_collections.py --store ba >> "%LOG%" 2>&1
%PYTHON% scripts\07_sync_parent_collections.py --store mk >> "%LOG%" 2>&1
REM In-stock-first reorder of menu parents (SK already handled by 03b)
%PYTHON% scripts\08_in_stock_first_reorder.py --store pl >> "%LOG%" 2>&1
%PYTHON% scripts\08_in_stock_first_reorder.py --store ba >> "%LOG%" 2>&1
%PYTHON% scripts\08_in_stock_first_reorder.py --store mk >> "%LOG%" 2>&1
REM Homepage curator for non-SK stores
%PYTHON% scripts\06_multi_curate_homepage.py --store pl >> "%LOG%" 2>&1
%PYTHON% scripts\06_multi_curate_homepage.py --store ba >> "%LOG%" 2>&1
%PYTHON% scripts\06_multi_curate_homepage.py --store mk >> "%LOG%" 2>&1

echo ==== weekly refresh complete %date% %time% ==== >> "%LOG%"
exit /b 0

:fail
echo ==== weekly refresh FAILED %date% %time% (exit %errorlevel%) ==== >> "%LOG%"
exit /b 1

"""
Playwright Router - API endpoints for browser automation via Playwright MCP server.
Provides RESTful endpoints for controlling browsers and web automation.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field

from utils.logger import get_logger
from services.playwright_mcp_service import PlaywrightMCPService
from dependencies import get_container


logger = get_logger("playwright_router")
router = APIRouter()


# Pydantic models for request/response validation

class NavigateRequest(BaseModel):
    url: str = Field(..., description="URL to navigate to")


class ScreenshotRequest(BaseModel):
    full_page: bool = Field(False, description="Take full page screenshot")
    element_ref: Optional[str] = Field(None, description="Element reference for targeted screenshot")


class ClickRequest(BaseModel):
    element_description: str = Field(..., description="Human-readable description of element to click")
    element_ref: str = Field(..., description="Element reference from page snapshot")
    button: str = Field("left", description="Mouse button to click (left, right, middle)")


class TypeRequest(BaseModel):
    element_description: str = Field(..., description="Human-readable description of input element")
    element_ref: str = Field(..., description="Element reference from page snapshot")
    text: str = Field(..., description="Text to type")
    submit: bool = Field(False, description="Whether to submit after typing (press Enter)")


class EvaluateRequest(BaseModel):
    function_code: str = Field(..., description="JavaScript function code to evaluate")
    element_ref: Optional[str] = Field(None, description="Element reference if function operates on specific element")


class WaitRequest(BaseModel):
    text: Optional[str] = Field(None, description="Text to wait for to appear")
    text_gone: Optional[str] = Field(None, description="Text to wait for to disappear")
    time_seconds: Optional[float] = Field(None, description="Time to wait in seconds")


class TabRequest(BaseModel):
    url: Optional[str] = Field(None, description="URL to open in new tab")


class SelectTabRequest(BaseModel):
    tab_index: int = Field(..., description="Index of tab to select")


class CloseTabRequest(BaseModel):
    tab_index: Optional[int] = Field(None, description="Index of tab to close (current tab if not specified)")


# Dependency to get Playwright service
async def get_playwright_service() -> PlaywrightMCPService:
    """FastAPI dependency to get Playwright MCP service"""
    container = await get_container()
    service = container.get_playwright_mcp_service()
    if not service:
        raise HTTPException(status_code=503, detail="Playwright MCP service not available")
    return service


# Browser Navigation Endpoints

@router.post("/navigate")
async def navigate_to_url(
    request: NavigateRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Navigate browser to a specific URL"""
    try:
        logger.info(f"Navigating to URL: {request.url}")
        result = await service.navigate(request.url)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Navigation failed"))
        
        return {
            "status": "success",
            "message": f"Successfully navigated to {request.url}",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in navigate endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Navigation error: {str(e)}")


@router.get("/snapshot")
async def get_page_snapshot(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Get accessibility snapshot of current page for finding elements"""
    try:
        logger.info("Getting page snapshot")
        result = await service.get_page_snapshot()
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to get page snapshot"))
        
        return {
            "status": "success",
            "message": "Page snapshot captured successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in snapshot endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Snapshot error: {str(e)}")


@router.post("/screenshot")
async def take_screenshot(
    request: ScreenshotRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Take a screenshot of the current page"""
    try:
        logger.info(f"Taking screenshot (full_page: {request.full_page})")
        result = await service.take_screenshot(
            full_page=request.full_page,
            element_ref=request.element_ref
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Screenshot failed"))
        
        return {
            "status": "success",
            "message": "Screenshot taken successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in screenshot endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Screenshot error: {str(e)}")


# Element Interaction Endpoints

@router.post("/click")
async def click_element(
    request: ClickRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Click an element on the page"""
    try:
        logger.info(f"Clicking element: {request.element_description}")
        result = await service.click_element(
            element_description=request.element_description,
            element_ref=request.element_ref,
            button=request.button
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Click failed"))
        
        return {
            "status": "success",
            "message": f"Successfully clicked {request.element_description}",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in click endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Click error: {str(e)}")


@router.post("/type")
async def type_text(
    request: TypeRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Type text into an element"""
    try:
        logger.info(f"Typing text into element: {request.element_description}")
        result = await service.type_text(
            element_description=request.element_description,
            element_ref=request.element_ref,
            text=request.text,
            submit=request.submit
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Type operation failed"))
        
        return {
            "status": "success",
            "message": f"Successfully typed text into {request.element_description}",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in type endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Type error: {str(e)}")


@router.post("/evaluate")
async def evaluate_javascript(
    request: EvaluateRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Evaluate JavaScript code on the page"""
    try:
        logger.info("Evaluating JavaScript code")
        result = await service.evaluate_javascript(
            function_code=request.function_code,
            element_ref=request.element_ref
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "JavaScript evaluation failed"))
        
        return {
            "status": "success",
            "message": "JavaScript evaluation completed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in evaluate endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation error: {str(e)}")


@router.post("/wait")
async def wait_for_condition(
    request: WaitRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Wait for text to appear/disappear or time to pass"""
    try:
        logger.info("Waiting for condition")
        result = await service.wait_for_element(
            text=request.text,
            text_gone=request.text_gone,
            time_seconds=request.time_seconds
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Wait condition failed"))
        
        return {
            "status": "success",
            "message": "Wait condition completed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in wait endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Wait error: {str(e)}")


# Tab Management Endpoints

@router.get("/tabs")
async def list_tabs(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """List all browser tabs"""
    try:
        logger.info("Listing browser tabs")
        result = await service.list_tabs()
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to list tabs"))
        
        return {
            "status": "success",
            "message": "Tabs listed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list tabs endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"List tabs error: {str(e)}")


@router.post("/tabs/new")
async def create_new_tab(
    request: TabRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Open a new browser tab"""
    try:
        logger.info(f"Creating new tab{f' with URL: {request.url}' if request.url else ''}")
        result = await service.new_tab(url=request.url)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to create new tab"))
        
        return {
            "status": "success",
            "message": f"New tab created{f' with URL: {request.url}' if request.url else ''}",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in new tab endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"New tab error: {str(e)}")


@router.post("/tabs/select")
async def select_tab(
    request: SelectTabRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Select a browser tab by index"""
    try:
        logger.info(f"Selecting tab: {request.tab_index}")
        result = await service.select_tab(tab_index=request.tab_index)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to select tab"))
        
        return {
            "status": "success",
            "message": f"Tab {request.tab_index} selected successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in select tab endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Select tab error: {str(e)}")


@router.post("/tabs/close")
async def close_tab(
    request: CloseTabRequest,
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Close a browser tab"""
    try:
        tab_info = f" {request.tab_index}" if request.tab_index is not None else " (current)"
        logger.info(f"Closing tab{tab_info}")
        result = await service.close_tab(tab_index=request.tab_index)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to close tab"))
        
        return {
            "status": "success",
            "message": f"Tab{tab_info} closed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in close tab endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Close tab error: {str(e)}")


# Browser Management Endpoints

@router.post("/browser/install")
async def install_browser(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Install browsers for Playwright"""
    try:
        logger.info("Installing browsers for Playwright")
        result = await service.install_browser()
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Browser installation failed"))
        
        return {
            "status": "success",
            "message": "Browsers installed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in browser install endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Browser installation error: {str(e)}")


@router.post("/browser/close")
async def close_browser(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Close the browser completely"""
    try:
        logger.info("Closing browser")
        result = await service.close_browser()
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to close browser"))
        
        return {
            "status": "success",
            "message": "Browser closed successfully",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in close browser endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Close browser error: {str(e)}")


@router.get("/browser/state")
async def get_browser_state(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Get current browser state"""
    try:
        logger.info("Getting browser state")
        result = await service.get_browser_state()
        
        return {
            "status": "success",
            "message": "Browser state retrieved successfully",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Error in browser state endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Browser state error: {str(e)}")


# Health and Status Endpoints

@router.get("/health")
async def health_check(
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Check health of Playwright MCP service"""
    try:
        health_info = await service.health_check()
        
        status_code = 200 if health_info["healthy"] else 503
        
        return {
            "status": "healthy" if health_info["healthy"] else "unhealthy",
            "message": "Playwright MCP service health check completed",
            "data": health_info
        }
        
    except Exception as e:
        logger.error(f"Error in health check endpoint: {e}")
        return {
            "status": "error",
            "message": "Health check failed",
            "error": str(e)
        }


# Convenience endpoint for quick automation workflows
@router.post("/automation/quick-test")
async def quick_automation_test(
    data: dict = Body(default={"url": "https://example.com"}),
    service: PlaywrightMCPService = Depends(get_playwright_service)
):
    """Quick automation test - navigate to URL and take screenshot"""
    try:
        url = data.get("url", "https://example.com")
        
        logger.info(f"Starting quick automation test for: {url}")
        
        # Navigate to URL
        nav_result = await service.navigate(url)
        if not nav_result["success"]:
            raise HTTPException(status_code=400, detail=f"Navigation failed: {nav_result.get('error')}")
        
        # Wait a moment for page to load
        await service.wait_for_element(time_seconds=2.0)
        
        # Take screenshot
        screenshot_result = await service.take_screenshot(full_page=True)
        if not screenshot_result["success"]:
            logger.warning(f"Screenshot failed: {screenshot_result.get('error')}")
        
        # Get page snapshot
        snapshot_result = await service.get_page_snapshot()
        if not snapshot_result["success"]:
            logger.warning(f"Snapshot failed: {snapshot_result.get('error')}")
        
        return {
            "status": "success",
            "message": f"Quick automation test completed for {url}",
            "data": {
                "navigation": nav_result,
                "screenshot": screenshot_result,
                "snapshot": snapshot_result
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in quick automation test: {e}")
        raise HTTPException(status_code=500, detail=f"Quick test error: {str(e)}")
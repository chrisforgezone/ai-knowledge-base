from typing import Optional

import httpx
from loguru import logger
from pydantic import BaseModel, Field
import asyncio

class GitHubRepoInfo(BaseModel):
    """GitHub 仓库基本信息数据模型。"""

    owner: str = Field(description="仓库所有者")
    repo: str = Field(description="仓库名称")
    stars: int = Field(description="Star 数量")
    forks: int = Field(description="Fork 数量")
    description: Optional[str] = Field(default=None, description="仓库描述")


def fetch_repo_info(
    repo_full_name: str,
    github_token: Optional[str] = None,
) -> GitHubRepoInfo:
    """从 GitHub API 获取指定仓库的基本信息。

    Args:
        repo_full_name: 仓库全名，格式为 "owner/repo"（如 "langchain-ai/langchain"）。
        github_token: GitHub Personal Access Token，可选。提供后可提升 API 速率限制。

    Returns:
        GitHubRepoInfo: 包含仓库 Star 数、Fork 数、描述的结构化数据。

    Raises:
        httpx.HTTPStatusError: 当 API 返回非 2xx 状态码时抛出。
        ValueError: 当 repo_full_name 格式不正确时抛出。
    """
    parts = repo_full_name.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(
            f"repo_full_name 格式必须为 'owner/repo'，实际值: {repo_full_name}"
        )

    owner, repo = parts
    url = f"https://api.github.com/repos/{owner}/{repo}"

    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    logger.info(f"正在获取 GitHub 仓库信息: {owner}/{repo}")
    with httpx.Client(timeout=httpx.Timeout(30)) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    data = response.json()
    repo_info = GitHubRepoInfo(
        owner=owner,
        repo=repo,
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        description=data.get("description"),
    )
    logger.info(
        f"成功获取 {owner}/{repo} 信息: "
        f"Stars={repo_info.stars}, Forks={repo_info.forks}"
    )
    return repo_info

async def fetch_repo_info_v2(
    repo_full_name: str,
    github_token: Optional[str] = None,
) -> GitHubRepoInfo:
    """从 GitHub API 获取指定仓库的基本信息。
    Args:
        repo_full_name: 仓库全名，格式为 "owner/repo"（如 "langchain-ai/langchain"）。
        github_token: GitHub Personal Access Token，可选。提供后可提升 API 速率限制。
    Returns:
        GitHubRepoInfo: 包含仓库 Star 数、Fork 数、描述的结构化数据。
    Raises:
        httpx.HTTPStatusError: 当 API 返回非 2xx 状态码时抛出。
        ValueError: 当 repo_full_name 格式不正确时抛出。
    """
    parts = repo_full_name.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(
            f"repo_full_name 格式必须为 'owner/repo'，实际值: {repo_full_name}"
        )
    owner, repo = parts
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    logger.info(f"正在获取 GitHub 仓库信息: {owner}/{repo}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    repo_info = GitHubRepoInfo(
        owner=owner,
        repo=repo,
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        description=data.get("description"),
    )
    logger.info(
        f"成功获取 {owner}/{repo} 信息: "
        f"Stars={repo_info.stars}, Forks={repo_info.forks}"
    )
    return repo_info

if __name__ == "__main__":
    fetch_repo_info("anomalyco/opencode")
    resp  = asyncio.run(fetch_repo_info_v2("anomalyco/opencode"))
    print(resp)
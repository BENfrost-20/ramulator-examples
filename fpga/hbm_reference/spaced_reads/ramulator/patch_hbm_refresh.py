#!/usr/bin/env python3
"""Enable channel-scoped HBM REFab in a disposable Ferrandi source checkout."""
from pathlib import Path
import subprocess
import sys

revision = "9a8ed857455d041524043bc5fb45eb7f07e6a731"
root = Path(sys.argv[1]).resolve(strict=True)
git = ["git", "-C", str(root)]
head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
if head != revision or subprocess.check_output([*git, "status", "--porcelain"], text=True):
    raise SystemExit("Use a clean, disposable checkout at the pinned Ferrandi revision")


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unexpected source layout for {old!r}")
    return text.replace(old, new, 1)


manager = root / "src/dram_controller/impl/refresh/all_bank_refresh.cpp"
scheduler = root / "src/dram_controller/impl/generic_dram_controller.cpp"
refresh = replace_once(manager.read_text(), "    int m_num_ranks = -1;",
                       "    int m_num_ranks = -1;\n    bool m_channel_scope = false;")
refresh = replace_once(refresh, '      m_num_ranks = m_dram->get_level_size("rank");',
                       '      m_num_ranks = m_dram->get_level_size("rank");\n'
                       '      m_channel_scope = m_num_ranks < 0 && m_dram->get_level_size("pseudochannel") > 0;')
refresh = replace_once(refresh, "        for (int r = 0; r < m_num_ranks; r++) {",
                       "        const int targets = m_channel_scope ? 1 : m_num_ranks;\n"
                       "        for (int r = 0; r < targets; r++) {")
refresh = replace_once(refresh, "          addr_vec[1] = r;",
                       "          // A channel-wide HBM command applies timing to both pseudochannels.\n"
                       "          if (!m_channel_scope) addr_vec[1] = r;")
controller = '#include <cstdio>\n' + scheduler.read_text()
issue = "        m_dram->issue_command(req_it->command, req_it->addr_vec);"
controller = replace_once(
    controller, issue,
    issue + "\n"
    '        if (m_channel_id == 0 && m_dram->get_level_size("pseudochannel") > 0 &&\n'
    '            m_dram->m_commands(req_it->command) == "REFab") {\n'
    '          std::fprintf(stderr, "ISSUED_REFab channel=0 tick=%llu\\n",\n'
    '                       static_cast<unsigned long long>(m_clk));\n'
    '        }',
)
# Preserve line endings used by the pinned files.
for path, text in ((manager, refresh), (scheduler, controller)):
    ending = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    path.write_bytes(text.replace("\n", ending).encode())

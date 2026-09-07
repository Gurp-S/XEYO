import { Box, Text, useStdout } from "ink";
import React from "react";
import { LOGO_COMPACT, LOGO_GLYPH } from "../logo.js";
import { clipPath, g, isAscii, reducedMotion, theme } from "../theme.js";
import type { CliConfig } from "../types.js";

type Props = {
  config: CliConfig;
  version?: string;
  connected?: boolean | null;
};

/**
 * 欢迎首屏：品牌标识 + 一行上下文，无仪表盘装饰。
 */
export function WelcomeDash({
  config,
  version = "0.1.0",
  connected = null,
}: Props) {
  const { stdout } = useStdout();
  const cols = stdout?.columns ?? 80;
  const narrow = cols < 72;
  const showLogo = !isAscii() && !reducedMotion() && cols >= 96;
  const t = theme();
  const gly = g();
  const mark = isAscii() ? gly.mark : LOGO_GLYPH;
  const cwdShort = clipPath(config.cwd, narrow ? 36 : 48);
  const model =
    config.model ||
    (config.provider === "deepseek" ? "deepseek-chat" : config.provider);

  const status =
    connected === null
      ? { color: t.muted, text: "…" }
      : connected
        ? { color: t.success, text: `${gly.live} online` }
        : { color: t.warning, text: `${gly.idle} offline` };

  return (
    <Box flexDirection="column" marginBottom={1} paddingY={1}>
      {showLogo ? (
        <Box marginBottom={1}>
          <Text color={t.accent}>{LOGO_COMPACT}</Text>
        </Box>
      ) : null}

      <Box>
        <Text color={t.accent} bold>
          {mark} XEYO
        </Text>
        <Text color={t.muted} dimColor>
          {" "}
          v{version}
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color={t.soft}>I am XEYO</Text>
        <Text color={t.muted} dimColor>
          {" "}
          · coding agent
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color={t.muted} dimColor>
          {cwdShort}
        </Text>
        <Text color={t.muted} dimColor>
          {" "}
          · {model}
        </Text>
        {config.agentMode !== "agent" ? (
          <Text color={t.warning}> · {config.agentMode}</Text>
        ) : null}
        <Text color={t.muted} dimColor>
          {" "}
          ·{" "}
        </Text>
        <Text color={status.color}>{status.text}</Text>
      </Box>

      {connected === false ? (
        <Box marginTop={1}>
          <Text color={t.warning}>
            {gly.warn} Start engine →{" "}
            <Text color={t.accent} bold>
              py -3.11 -m cli serve
            </Text>
          </Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.muted} dimColor>
          {gly.prompt} type a message · /help · /demo
        </Text>
      </Box>
    </Box>
  );
}

/* Android audio uses our DirectSound mixer; there are no WinMM mixer devices. */
#include "host.h"

WINAPI_EXPORT("winmm.dll", mixerGetNumDevs, 0) { return 0; }

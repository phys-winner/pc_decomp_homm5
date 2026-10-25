/* Local UUID generation for the game's RPC dependency. No RPC transport. */
#include "host.h"
#include <stdlib.h>

/* https://learn.microsoft.com/en-us/windows/win32/api/rpcdce/nf-rpcdce-uuidcreate */
WINAPI_EXPORT("rpcrt4.dll", UuidCreate, 1)
{
    if (!void_vm_writable(ARG(0), 16)) return 87u;
    uint8_t uuid[16];
    arc4random_buf(uuid, sizeof uuid);
    uuid[7] = (uuid[7] & 15) | 0x40; /* GUID Data3 is little endian. */
    uuid[8] = (uuid[8] & 63) | 0x80;
    memcpy(GPTR(ARG(0)), uuid, sizeof uuid);
    return 0;
}

#pragma once
#include <stdint.h>
using u8 = uint8_t;
using u32 = uint32_t;
using u64 = uint64_t;
using Result = int32_t;
using Handle = uint32_t;
enum FS_ArchiveID : uint32_t {};
enum { PATH_BINARY = 2, FS_OPEN_READ = 1 };
struct FS_Path { u32 type; u32 size; const void* data; };
Result FSUSER_OpenFileDirectly(Handle*, FS_ArchiveID, FS_Path, FS_Path, u32, u32);
Result FSFILE_GetSize(Handle, u64*);
Result FSFILE_Close(Handle);
struct ExHeader_Info { u8 data[0x400]; };
enum FS_MediaType { MEDIATYPE_NAND = 0, MEDIATYPE_SD = 1, MEDIATYPE_GAME_CARD = 2 };
struct FS_ProgramInfo { u64 programId; FS_MediaType mediaType; u8 padding[4]; };
#define R_FAILED(r) ((r) < 0)
#define R_SUCCEEDED(r) ((r) >= 0)
inline int AtomicPostIncrement(int* p) { return (*p)++; }
inline int AtomicDecrement(int* p) { return --(*p); }
inline u32 IPC_MakeHeader(u32 id, u32 normal, u32 descriptors) {
    return (id << 16) | (normal << 6) | descriptors;
}
inline u32 IPC_Desc_StaticBuffer(u32 size, u32 id) { return (size << 14) | (id << 10) | 2; }
u32* getThreadCommandBuffer();
u32* getThreadStaticBuffers();
Result srvGetServiceHandle(Handle*, const char*);
Result svcSendSyncRequest(Handle);
Result svcCloseHandle(Handle);

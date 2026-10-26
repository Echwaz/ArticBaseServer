#include "3ds.h"
#include "loaderCustom.hpp"
#include "pxiRomFS.hpp"
#include <string.h>
#include <stdint.h>
extern "C" {
#include "csvc.h"
}

namespace ArticFunctions {

    static Handle loaderHandleCustom;
    static int loaderRefCountCustom;
    Result loaderInitCustom(void)
    {
        Result res;
        if (AtomicPostIncrement(&loaderRefCountCustom)) return 0;
        res = srvGetServiceHandle(&loaderHandleCustom, "Loader");
        if (R_FAILED(res)) AtomicDecrement(&loaderRefCountCustom);
        return res;
    }

    void loaderExitCustom(void)
    {
        if (AtomicDecrement(&loaderRefCountCustom)) return;
        svcCloseHandle(loaderHandleCustom);
    }

    Result LOADER_GetLastApplicationProgramInfo(ExHeader_Info* exheaderInfo)
    {
        Result ret = 0;
        u32 *cmdbuf = getThreadCommandBuffer();
        u32 *staticbufs = getThreadStaticBuffers();

        cmdbuf[0] = IPC_MakeHeader(0x102, 0, 0);

        u32 staticbufscpy[2] = {staticbufs[0], staticbufs[1]};
        staticbufs[0] = IPC_Desc_StaticBuffer(0x400, 0);
        staticbufs[1] = static_cast<u32>(reinterpret_cast<uintptr_t>(exheaderInfo));

        ret = svcSendSyncRequest(loaderHandleCustom);

        staticbufs[0] = staticbufscpy[0];
        staticbufs[1] = staticbufscpy[1];

        return R_FAILED(ret) ? ret : (Result)cmdbuf[1];
    }

    static Result RegisterTitle(u64* handle, u64 titleId, u8 mediaType)
    {
        FS_ProgramInfo title{};
        title.programId = titleId;
        title.mediaType = static_cast<FS_MediaType>(mediaType);
        u32* commands = getThreadCommandBuffer();
        commands[0] = IPC_MakeHeader(2, 8, 0);
        memcpy(&commands[1], &title, sizeof(title));
        FS_ProgramInfo update = title;
        if ((titleId >> 32) == 0x00040000 && R_SUCCEEDED(amInit())) {
            u64 updateId = (titleId & 0xFFFFFFFFULL) | 0x0004000E00000000ULL;
            AM_TitleEntry entry{};
            if (R_SUCCEEDED(AM_GetTitleInfo(MEDIATYPE_SD, 1, &updateId, &entry))) {
                update.programId = updateId;
                update.mediaType = MEDIATYPE_SD;
            }
            amExit();
        }
        commands = getThreadCommandBuffer();
        commands[0] = IPC_MakeHeader(2, 8, 0);
        memcpy(&commands[1], &title, sizeof(title));
        memcpy(&commands[5], &update, sizeof(update));
        Result res = svcSendSyncRequest(loaderHandleCustom);
        if (R_SUCCEEDED(res)) res = static_cast<Result>(commands[1]);
        if (R_SUCCEEDED(res)) memcpy(handle, &commands[2], sizeof(*handle));
        return res;
    }

    static Result UnregisterTitle(u64 handle)
    {
        u32* commands = getThreadCommandBuffer();
        commands[0] = IPC_MakeHeader(3, 2, 0);
        memcpy(&commands[1], &handle, sizeof(handle));
        Result res = svcSendSyncRequest(loaderHandleCustom);
        return R_FAILED(res) ? res : static_cast<Result>(commands[1]);
    }

    void LOADER_ProbeTitleRomFSPXI(PxiRomFSReport* report, u64 titleId, u8 mediaType)
    {
        *report = {};
        Result res = loaderInitCustom();
        if (R_SUCCEEDED(res)) {
            u64 program;
            res = RegisterTitle(&program, titleId, mediaType);
            if (R_SUCCEEDED(res)) {
                ProbePxiProgramRomFS(report, program);
                Result cleanup = UnregisterTitle(program);
                res = R_FAILED(report->result) ? report->result : cleanup;
            }
            loaderExitCustom();
        }
        report->result = res;
    }

    static Result GetRegisteredInfo(ExHeader_Info* output, u64 programHandle) {
        u32* commands = getThreadCommandBuffer();
        u32* staticBuffers = getThreadStaticBuffers();
        const u32 saved[2] = {staticBuffers[0], staticBuffers[1]};
        commands[0] = IPC_MakeHeader(4, 2, 0);
        memcpy(&commands[1], &programHandle, sizeof(programHandle));
        staticBuffers[0] = IPC_Desc_StaticBuffer(sizeof(*output), 0);
        staticBuffers[1] = static_cast<u32>(reinterpret_cast<uintptr_t>(output));
        Result res = svcSendSyncRequest(loaderHandleCustom);
        if (R_SUCCEEDED(res)) res = static_cast<Result>(commands[1]);
        staticBuffers[0] = saved[0];
        staticBuffers[1] = saved[1];
        return res;
    }

    static PxiReadSession cachedRomFS;
    static Handle cachedFsFile;
    static u64 cachedFsSize;
    static u64 cachedProgram;
    static u64 cachedTitle;
    static u8 cachedMedia;
    static bool cachedLoaderOpen;
    static bool cachedUpdate;

    void LOADER_CloseRomFSCache() {
        if (cachedFsFile) FSFILE_Close(cachedFsFile);
        cachedFsFile = 0;
        ClosePxiProgramFile(cachedRomFS);
        if (cachedLoaderOpen) {
            UnregisterTitle(cachedProgram);
            loaderExitCustom();
        }
        cachedLoaderOpen = false;
        cachedProgram = cachedTitle = 0;
    }

    static Result OpenLoaderFile(Handle* file, u64* size, u64 program, bool code, bool update = false) {
        Handle service = 0;
        Result res = svcControlService(SERVICEOP_STEAL_CLIENT_SESSION, &service, "fs:LDR");
        if (R_FAILED(res)) return res;
        const u32 path[3] = {code ? 1u : (update ? 5u : 0u), code ? 0x646F632Eu : 0u, code ? 0x65u : 0u};
        fsUseSession(service);
        res = FSUSER_OpenFileDirectly(file, static_cast<FS_ArchiveID>(0x2345678E),
            {PATH_BINARY, sizeof(program), &program}, {PATH_BINARY, sizeof(path), path}, FS_OPEN_READ, 0);
        fsEndUseSession();
        svcCloseHandle(service);
        if (R_SUCCEEDED(res)) {
            res = FSFILE_GetSize(*file, size);
            if (R_FAILED(res)) { FSFILE_Close(*file); *file = 0; }
        }
        return res;
    }

    Result LOADER_GetTitleCodeSize(u64* size, u64 titleId, u8 mediaType) {
        LOADER_CloseRomFSCache();
        *size = 0;
        Result res = loaderInitCustom();
        if (R_FAILED(res)) return res;
        u64 program;
        res = RegisterTitle(&program, titleId, mediaType);
        if (R_SUCCEEDED(res)) {
            ExHeader_Info info{};
            res = GetRegisteredInfo(&info, program);
            Handle file = 0;
            if (R_SUCCEEDED(res)) res = OpenLoaderFile(&file, size, program, true);
            if (file) FSFILE_Close(file);
            const Result cleanup = UnregisterTitle(program);
            if (R_SUCCEEDED(res)) res = cleanup;
        }
        loaderExitCustom();
        return res;
    }

    Result LOADER_ReadTitleCode(void* data, u32 capacity, u32* bytesRead, u64 titleId, u8 mediaType) {
        LOADER_CloseRomFSCache();
        *bytesRead = 0;
        Result res = loaderInitCustom();
        if (R_FAILED(res)) return res;
        u64 program;
        res = RegisterTitle(&program, titleId, mediaType);
        if (R_SUCCEEDED(res)) {
            ExHeader_Info info{};
            res = GetRegisteredInfo(&info, program);
            PxiReadSession file;
            if (R_SUCCEEDED(res)) {
                Handle loaderFile = 0;
                u64 size = 0;
                res = OpenLoaderFile(&loaderFile, &size, program, true);
                if (R_SUCCEEDED(res)) {
                    if (size > capacity) res = static_cast<Result>(0xE0E046C1);
                    else res = FSFILE_Read(loaderFile, bytesRead, 0, data, static_cast<u32>(size));
                    FSFILE_Close(loaderFile);
                }
                if (R_FAILED(res)) {
                    res = OpenPxiProgramFile(file, program, true);
                    if (R_SUCCEEDED(res)) {
                        if (file.size > capacity) res = static_cast<Result>(0xE0E046C1);
                        else res = ReadPxiProgramFile(file, 0, static_cast<u32>(file.size), data, bytesRead);
                    }
                }
            }
            ClosePxiProgramFile(file);
            const Result cleanup = UnregisterTitle(program);
            if (R_SUCCEEDED(res)) res = cleanup;
        }
        loaderExitCustom();
        return res;
    }

    Result LOADER_ReadTitleRomFSPXI(void* data, u32 size, u64 offset,
                                  u32* bytesRead, u64* fileSize, u64 titleId, u8 mediaType, bool update)
    {
        *bytesRead = 0;
        *fileSize = 0;
        if ((!cachedRomFS.fileOpen && !cachedFsFile) || titleId != cachedTitle || mediaType != cachedMedia || update != cachedUpdate) {
            LOADER_CloseRomFSCache();
            Result res = loaderInitCustom();
            if (R_FAILED(res)) return res;
            res = RegisterTitle(&cachedProgram, titleId, mediaType);
            if (R_FAILED(res)) { loaderExitCustom(); return res; }
            cachedLoaderOpen = true;
            ExHeader_Info info{};
            res = GetRegisteredInfo(&info, cachedProgram);
            if (R_SUCCEEDED(res)) {
                res = OpenLoaderFile(&cachedFsFile, &cachedFsSize, cachedProgram, false, update);
                if (R_FAILED(res) && !update) res = OpenPxiProgramFile(cachedRomFS, cachedProgram, false);
            }
            if (R_FAILED(res)) { LOADER_CloseRomFSCache(); return res; }
            cachedTitle = titleId;
            cachedMedia = mediaType;
            cachedUpdate = update;
        }
        *fileSize = cachedFsFile ? cachedFsSize : cachedRomFS.size;
        Result res;
        if (cachedFsFile) {
            if (offset > *fileSize || size > *fileSize - offset) res = static_cast<Result>(0xE0E046C1);
            else res = FSFILE_Read(cachedFsFile, bytesRead, offset, data, size);
        } else res = ReadPxiProgramFile(cachedRomFS, offset, size, data, bytesRead);
        if (R_FAILED(res)) LOADER_CloseRomFSCache();
        return res;
    }

    Result LOADER_ProbeTitleRomFS(u64* size, u64 titleId, u8 mediaType)
    {
        *size = 0;
        Result res = loaderInitCustom();
        if (R_FAILED(res)) return res;
        u64 program;
        res = RegisterTitle(&program, titleId, mediaType);
        if (R_SUCCEEDED(res)) {
            const u32 path[] = {0, 0, 0};
            FS_Path archivePath{PATH_BINARY, sizeof(program), &program};
            FS_Path filePath{PATH_BINARY, sizeof(path), path};
            Handle file;
            res = FSUSER_OpenFileDirectly(&file, static_cast<FS_ArchiveID>(0x2345678E),
                                         archivePath, filePath, FS_OPEN_READ, 0);
            if (R_SUCCEEDED(res)) {
                res = FSFILE_GetSize(file, size);
                Result close = FSFILE_Close(file);
                if (R_SUCCEEDED(res)) res = close;
            }
            Result cleanup = UnregisterTitle(program);
            if (R_SUCCEEDED(res)) res = cleanup;
        }
        loaderExitCustom();
        return res;
    }

    Result LOADER_GetTitleProgramInfo(ExHeader_Info* output, u64 titleId, u8 mediaType)
    {
        static_assert(sizeof(FS_ProgramInfo) == 0x10);
        static_assert(sizeof(ExHeader_Info) == 0x400);
        Result res = loaderInitCustom();
        if (R_FAILED(res)) return res;

        u64 programHandle;
        res = RegisterTitle(&programHandle, titleId, mediaType);
        if (R_FAILED(res)) {
            loaderExitCustom();
            return res;
        }

        u32* commands = getThreadCommandBuffer();
        u32* staticBuffers = getThreadStaticBuffers();
        u32 savedBuffers[2] = {staticBuffers[0], staticBuffers[1]};
        commands[0] = IPC_MakeHeader(4, 2, 0);
        memcpy(&commands[1], &programHandle, sizeof(programHandle));
        staticBuffers[0] = IPC_Desc_StaticBuffer(sizeof(*output), 0);
        staticBuffers[1] = static_cast<u32>(reinterpret_cast<uintptr_t>(output));
        res = svcSendSyncRequest(loaderHandleCustom);
        if (R_SUCCEEDED(res)) res = static_cast<Result>(commands[1]);
        staticBuffers[0] = savedBuffers[0];
        staticBuffers[1] = savedBuffers[1];

        Result cleanup = UnregisterTitle(programHandle);
        loaderExitCustom();
        return R_FAILED(res) ? res : cleanup;
    }
}

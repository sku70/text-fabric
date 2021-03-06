import array,collections,functools
from .helpers import *

def getOtypeInfo(info, otype):
    result = (otype[-2], otype[-1], len(otype) - 2 + otype[-1])
    info('slot={}:1-{};node-{}'.format(*result))
    return result

def levels(info, error, otype, oslots):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    otypeCount = collections.Counter()
    otypeMin = {}
    otypeMax = {}
    slotSetLengths = collections.Counter()
    info('get ranking of otypes')
    for k in range(len(oslots) - 1):
        ntp = otype[k]
        otypeCount[ntp] += 1
        slotSetLengths[ntp] += len(oslots[k])
        tfn = k + maxSlot + 1
        if ntp not in otypeMin: otypeMin[ntp] = tfn
        if ntp not in otypeMax or otypeMax[ntp] < tfn: otypeMax[ntp] = tfn
    result = tuple(sorted(
        ((ntp, slotSetLengths[ntp]/otypeCount[ntp], otypeMin[ntp], otypeMax[ntp]) for ntp in otypeCount),
        key=lambda x: -x[1],
    )+[(slotType, 1, 1, maxSlot)])
    info('results:')
    for (otp, av, omin, omax) in result:
        info('{:<15}: {:>8} {{{}-{}}}'.format(otp, round(av, 2), omin, omax), tm=False)
    return result

def order(info, error, otype, oslots, levels):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    info('assigning otype levels to nodes')
    otypeLevels = dict(((x[0], i) for (i, x) in enumerate(levels)))
    otypeRank = lambda n: otypeLevels[slotType if n < maxSlot+1 else otype[n-maxSlot-1]]
    def before(na,nb):
        if na < maxSlot + 1:
            a = na
            sa = {a}
        else:
            a = na - maxSlot
            sa = set(oslots[a-1])
        if nb < maxSlot + 1:
            b = nb
            sb = {b}
        else:
            b = nb - maxSlot
            sb = set(oslots[b-1])
        oa = otypeRank(na)
        ob = otypeRank(nb)
        if sa == sb: return 0 if oa == ob else -1 if oa < ob else 1
        if sa > sb: return -1
        if sa < sb: return 1
        am = min(sa - sb)
        bm = min(sb - sa)
        return -1 if am < bm else 1 if bm < am else None

    canonKey = functools.cmp_to_key(before)
    info('sorting nodes')
    nodes = sorted(range(1, maxNode+1), key=canonKey)
    return array.array('I', nodes)

def rank(info, error, otype, order):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    info('ranking nodes')
    nodesRank = dict(((n,i) for (i,n) in enumerate(order)))
    return array.array('I', (nodesRank[n] for n in range(1, maxNode+1)))

def levUp(info, error, otype, oslots, rank):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    info('making inverse of edge feature oslots')
    oslotsInv = {}
    for (k, mList) in enumerate(oslots[0:-1]):
        for m in mList:
            oslotsInv.setdefault(m, set()).add(k+1+maxSlot)
    info('listing embedders of all nodes')
    embedders = []
    for n in range(1, maxSlot+1):
        contentEmbedders = oslotsInv[n]
        embedders.append(tuple(sorted(
            [m for m in contentEmbedders if rank[m-1] < rank[n-1]],
            key=lambda k: -rank[k-1],
        )))
    for n in range(maxSlot+1, maxNode+1):
        mList = oslots[n-maxSlot-1]
        if len(mList) == 0:
            embedders.append(tuple())
        else:
            contentEmbedders = functools.reduce(
                lambda x,y: x & oslotsInv[y],
                mList[1:], oslotsInv[mList[0]],
            )
            embedders.append(tuple(sorted(
                [m for m in contentEmbedders if rank[m-1] < rank[n-1]],
                key=lambda k: -rank[k-1],
            )))
    return tuple(embedders)

def levDown(info, error, otype, levUp, rank):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    info('inverting embedders')
    inverse = {}
    for n in range(maxSlot+1, maxNode+1):
        for m in levUp[n-1]:
            inverse.setdefault(m, set()).add(n)
    info('turning embeddees into list')
    embeddees = []
    for n in range(maxSlot+1, maxNode+1):
        embeddees.append(tuple(sorted(
            inverse.get(n, []),
            key=lambda m: rank[m-1],
        )))
    return tuple(embeddees)

def boundary(info, error, otype, oslots, rank):
    firstSlotsD = {}
    lastSlotsD = {}
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    for (k, mList) in enumerate(oslots[0:-1]):
        firstSlotsD.setdefault(mList[0], []).append(k+1+maxSlot)
        lastSlotsD.setdefault(mList[-1], []).append(k+1+maxSlot)
    firstSlots = []
    lastSlots = []
    for n in range(1, maxSlot+1):
        firstSlots.append(tuple(sorted(firstSlotsD.get(n, []), key=lambda k: -rank[k-1])))
        lastSlots.append(tuple(sorted(lastSlotsD.get(n, []), key=lambda k: rank[k-1])))
    return (tuple(firstSlots), tuple(lastSlots))

def sections(info, error, otype, oslots, otext, levUp, levels, *sFeats):
    (slotType, maxSlot, maxNode) = getOtypeInfo(info, otype)
    support = dict(((o[0], (o[2], o[3])) for o in levels))
    sTypes = itemize(otext['sectionTypes'], ',')
    sec1 = {}
    sec2 = {}
    c1 = 0
    c2 = 0
    for n2 in range(*support[sTypes[2]]):
        n0 = tuple(x for x in levUp[n2-1] if otype[x - maxSlot - 1] == sTypes[0])[0]
        n1 = tuple(x for x in levUp[n2-1] if otype[x - maxSlot - 1] == sTypes[1])[0]
        n1s = sFeats[1][n1]
        n2s = sFeats[2][n2]
        if n0 not in sec1: sec1[n0] = {}
        if n1s not in sec1[n0]:
            sec1[n0][n1s] = n1
            c1 += 1
        sec2.setdefault(n0, {}).setdefault(n1s, {})[n2s] = n2
        c2 += 1
    info('{} {}s and {} {}s indexed'.format(c1, sTypes[1], c2, sTypes[2]))
    return (sec1, sec2)

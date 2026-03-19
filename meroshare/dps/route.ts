import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
    try {
        // First try to fetch live
        const response = await fetch('https://meroshare.cdsc.com.np/api/casba/bank/', {
            next: { revalidate: 86400 }
        });

        if (response.ok) {
            const data = await response.json();
            const formattedDps = data.map((item: any) => ({
                id: item.id.toString(),
                name: item.name,
                code: item.code
            }));
            return NextResponse.json(formattedDps);
        }
    } catch (error) {
        console.warn('Failed to fetch live DPs, falling back to local file');
    }

    // Fallback to local dps.json if live fetch fails
    try {
        const filePath = path.join(process.cwd(), 'dps.json');
        if (fs.existsSync(filePath)) {
            const fileData = fs.readFileSync(filePath, 'utf8');
            return NextResponse.json(JSON.parse(fileData));
        }
    } catch (error) {
        console.error('Failed to read dps.json');
    }

    // Hardcoded fallback for critical banks
    return NextResponse.json([
        { id: "13100", name: "NIC ASIA Bank Limited", code: "NIC" },
        { id: "10200", name: "Nabil Bank Limited", code: "NABIL" },
        { id: "11600", name: "Global IME Bank Limited", code: "GBIME" },
        { id: "11000", name: "Rastriya Banijya Bank Limited", code: "RBB" }
    ]);
}

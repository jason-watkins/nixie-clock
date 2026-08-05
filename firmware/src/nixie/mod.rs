const NUMBER_MAP: [u8; 10] = [6, 4, 5, 1, 0, 9, 8, 2, 3, 7];
// TODO: Make this store proper GPIO pins
const BCD_PINS: [[u8; 4]; 4] = [
    [4, 15, 17, 6],   // M1,
    [18, 7, 5, 16],   // M10,
    [47, 12, 10, 14], // H1
    [9, 13, 21, 11],  // H10
];

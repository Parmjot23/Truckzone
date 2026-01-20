import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import * as React from 'react';
import { Alert, ScrollView, View } from 'react-native';
import { RouteProp, useRoute, useNavigation } from '@react-navigation/native';
import { Button, Card, Divider, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import { apiClient } from '@/services/apiClient';
import VehicleHistoryModal from '@/components/VehicleHistoryModal';

type ChecklistStatus = 'pass' | 'fail' | 'na';

type ChecklistItem = {
  id: string;
  label: string;
  code: string;
};

type ChecklistSection = {
  code: string;
  title: string;
  items: ChecklistItem[];
};

const CHECKLIST_SECTIONS: ChecklistSection[] = [
  {
    code: 'A',
    title: 'Instruments & Controls',
    items: [
      { id: 'instruments-accelerator-pedal', code: 'a', label: 'Accelerator pedal' },
      { id: 'instruments-brake-pedal', code: 'b', label: 'Brake pedal' },
      { id: 'instruments-clutch', code: 'c', label: 'Clutch' },
      { id: 'instruments-engine-shutdown', code: 'd', label: 'Engine shut down' },
      { id: 'instruments-neutral-safety-switch', code: 'e', label: 'Neutral safety switch' },
      { id: 'instruments-shift-pattern', code: 'f', label: 'Shift pattern / if equipped' },
      { id: 'instruments-controls-switches', code: 'g', label: 'Controls, switches' },
      { id: 'instruments-indicators', code: 'h', label: 'Instrument / indicator / lamp' },
      { id: 'instruments-speedometer', code: 'i', label: 'Speedometer' },
      { id: 'instruments-steering-travel', code: 'j', label: 'Steering wheel & travel' },
      { id: 'instruments-steering-tilt', code: 'k', label: 'Steering wheel tilt & telescope' },
      { id: 'instruments-horn', code: 'l', label: 'Horn' },
      { id: 'instruments-wipers', code: 'm', label: 'Windshield wiper & washer' },
      { id: 'instruments-heater-defroster', code: 'n', label: 'Heater / defroster' },
    ],
  },
  {
    code: 'B',
    title: 'Interior & Equipment',
    items: [
      { id: 'interior-windshield', code: 'a', label: 'Windshield' },
      { id: 'interior-side-windows', code: 'b', label: 'Side windows' },
      { id: 'interior-rear-window', code: 'c', label: 'Rear window' },
      { id: 'interior-rearview-mirrors', code: 'd', label: 'Rearview mirrors' },
      { id: 'interior-sun-visor', code: 'e', label: 'Sun visor' },
      { id: 'interior-fire-extinguisher', code: 'f', label: 'Fire extinguisher' },
      { id: 'interior-hazard-warning-kit', code: 'g', label: 'Hazard warning kit' },
      { id: 'interior-seats-belts-airbags', code: 'h', label: 'Seats, seat belts, air bags' },
    ],
  },
  {
    code: 'C',
    title: 'Body & Exterior',
    items: [
      { id: 'exterior-body', code: 'a', label: 'Body & cargo body' },
      { id: 'exterior-hood', code: 'b', label: 'Hood' },
      { id: 'exterior-cab-mounts', code: 'c', label: 'Cab mounts, suspension or tilt' },
      { id: 'exterior-doors', code: 'd', label: 'Doors' },
      { id: 'exterior-grab-handles', code: 'e', label: 'Grab handle & step' },
      { id: 'exterior-bumper', code: 'f', label: 'Bumper' },
      { id: 'exterior-fenders', code: 'g', label: 'Fenders & mud flaps' },
      { id: 'exterior-load-securement', code: 'h', label: 'Load securement points' },
      { id: 'exterior-headache-rack', code: 'i', label: 'Chain / headache rack' },
      { id: 'exterior-attached-equipment', code: 'j', label: 'Attached equipment' },
      { id: 'exterior-cmvss-label', code: 'k', label: 'CMVSS compliance label' },
    ],
  },
  {
    code: 'D',
    title: 'Lamps',
    items: [
      { id: 'lamps-headlamp-daytime', code: 'a', label: 'Headlamp, & daytime lights' },
      { id: 'lamps-tail-marker', code: 'b', label: 'Tail, marker, I.D. & clearance' },
      { id: 'lamps-brake-turn-hazard', code: 'c', label: 'Brake, turn & hazard' },
      { id: 'lamps-driving-fog-licence', code: 'd', label: 'Driving, fog & licence plate' },
      { id: 'lamps-reflectors', code: 'e', label: 'Reflector, reflective tape / mudflap' },
    ],
  },
  {
    code: 'E',
    title: 'Powertrain & Frame',
    items: [
      { id: 'powertrain-fuel-system', code: 'a', label: 'Fuel system' },
      { id: 'powertrain-exhaust', code: 'b', label: 'Exhaust' },
      { id: 'powertrain-frame-rails', code: 'c', label: 'Frame rails, mounts' },
      { id: 'powertrain-drive-shaft', code: 'd', label: 'Drive shaft' },
      { id: 'powertrain-engine-mounts', code: 'e', label: 'Engine / trans. mounts' },
      { id: 'powertrain-power-steering', code: 'f', label: 'Power steering' },
      { id: 'powertrain-battery', code: 'g', label: 'Battery' },
      { id: 'powertrain-wiring', code: 'h', label: 'Wiring' },
    ],
  },
  {
    code: 'F',
    title: 'Steering & Suspension',
    items: [
      { id: 'steering-linkage', code: 'a', label: 'Steering linkage' },
      { id: 'steering-ball-joints', code: 'b', label: 'Ball joints, kingpins' },
      { id: 'steering-spring-elements', code: 'c', label: 'Spring elements & attachment' },
      { id: 'steering-brackets', code: 'd', label: 'Brackets, arms, linkage' },
      { id: 'steering-air-suspension', code: 'e', label: 'Air suspension, tag axle' },
      { id: 'steering-shock-absorbers', code: 'f', label: 'Shock absorbers' },
    ],
  },
  {
    code: 'G',
    title: 'Air Brake System',
    items: [
      { id: 'air-brake-compressor', code: 'a', label: 'Compressor' },
      { id: 'air-brake-build-up', code: 'b', label: 'Build up, governor, leakage' },
      { id: 'air-brake-low-pressure-warning', code: 'c', label: 'Low pressure warning' },
      { id: 'air-brake-check-valves', code: 'd', label: 'One & two-way check valves' },
      { id: 'air-brake-controls-valves', code: 'e', label: 'Controls, valves, lines & fittings' },
      { id: 'air-brake-tractor-protection', code: 'f', label: 'Tractor protection system' },
      { id: 'air-brake-parking-emergency', code: 'g', label: 'Parking / emergency operation' },
      { id: 'air-brake-mechanical-components', code: 'h', label: 'Mechanical components' },
      { id: 'air-brake-drum-lining', code: 'i', label: 'Drum & lining / for cracks' },
      { id: 'air-brake-rotor-caliper', code: 'j', label: 'Rotor & caliper / for cracks' },
      { id: 'air-brake-wheel-seals', code: 'k', label: 'Check for wheel seal leaks' },
      { id: 'air-brake-abs', code: 'l', label: 'ABS / no malfunction lights' },
      { id: 'air-brake-stroke', code: 'm', label: 'Brake stroke (adjustment)' },
    ],
  },
  {
    code: 'H',
    title: 'Tire & Wheel',
    items: [
      { id: 'tire-tread-condition', code: 'a', label: 'Tread condition' },
      { id: 'tire-sidewall-damage', code: 'b', label: 'Sidewall damage' },
    ],
  },
  {
    code: 'I',
    title: 'Coupling Device',
    items: [
      { id: 'coupling-device-fifth-wheel', code: 'a', label: 'Fifth wheel, trailer hitch' },
      { id: 'coupling-device-cords', code: 'b', label: 'Trailer air and electrical cords' },
    ],
  },
];

const PUSHROD_MEASUREMENT_IDS = [
  'pushrod-lf',
  'pushrod-lc',
  'pushrod-lr',
  'pushrod-rf',
  'pushrod-rc',
  'pushrod-rr',
] as const;

const TREAD_DEPTH_IDS = [
  'tire-depth-lf',
  'tire-depth-lc',
  'tire-depth-lr',
  'tire-depth-rf',
  'tire-depth-rc',
  'tire-depth-rr',
] as const;

const TIRE_PRESSURE_IDS = [
  'tire-pressure-lf',
  'tire-pressure-lc',
  'tire-pressure-lr',
  'tire-pressure-rf',
  'tire-pressure-rc',
  'tire-pressure-rr',
] as const;

const PUSHROD_MEASUREMENT_LABELS: Record<(typeof PUSHROD_MEASUREMENT_IDS)[number], string> = {
  'pushrod-lf': 'LF',
  'pushrod-lc': 'LM',
  'pushrod-lr': 'LR',
  'pushrod-rf': 'RF',
  'pushrod-rc': 'RM',
  'pushrod-rr': 'RR',
};

const TREAD_DEPTH_LABELS: Record<(typeof TREAD_DEPTH_IDS)[number], string> = {
  'tire-depth-lf': 'LF',
  'tire-depth-lc': 'LM',
  'tire-depth-lr': 'LR',
  'tire-depth-rf': 'RF',
  'tire-depth-rc': 'RM',
  'tire-depth-rr': 'RR',
};

const TIRE_PRESSURE_LABELS: Record<(typeof TIRE_PRESSURE_IDS)[number], string> = {
  'tire-pressure-lf': 'LF',
  'tire-pressure-lc': 'LM',
  'tire-pressure-lr': 'LR',
  'tire-pressure-rf': 'RF',
  'tire-pressure-rc': 'RM',
  'tire-pressure-rr': 'RR',
};

const PUSHROD_MEASUREMENT_LAYOUT: (typeof PUSHROD_MEASUREMENT_IDS)[number][][] = [
  ['pushrod-lf', 'pushrod-lc', 'pushrod-lr'],
  ['pushrod-rf', 'pushrod-rc', 'pushrod-rr'],
];

const TREAD_DEPTH_LAYOUT: (typeof TREAD_DEPTH_IDS)[number][][] = [
  ['tire-depth-lf', 'tire-depth-lc', 'tire-depth-lr'],
  ['tire-depth-rf', 'tire-depth-rc', 'tire-depth-rr'],
];

const createMeasurementMap = <T extends readonly string[]>(ids: T) =>
  ids.reduce<Record<T[number], string>>((acc, id) => {
    acc[id] = '';
    return acc;
  }, {} as Record<T[number], string>);

const mergeMeasurementValues = <T extends Record<string, string>>(
  base: T,
  incoming: unknown,
): T => {
  if (!incoming || typeof incoming !== 'object') {
    return base;
  }

  const result = { ...base };
  Object.entries(incoming as Record<string, unknown>).forEach(([key, value]) => {
    if (Object.prototype.hasOwnProperty.call(result, key) && (typeof value === 'string' || typeof value === 'number')) {
      result[key as keyof T] = String(value) as T[keyof T];
    }
  });

  return result;
};

type MeasurementMaps = {
  pushrodStroke: Record<(typeof PUSHROD_MEASUREMENT_IDS)[number], string>;
  treadDepth: Record<(typeof TREAD_DEPTH_IDS)[number], string>;
  tirePressure: Record<(typeof TIRE_PRESSURE_IDS)[number], string>;
};

type RouteParams = {
  jobId?: string;
  workOrderNumber?: string | number;
  customerName?: string;
  location?: string;
  businessInfo?: {
    name?: string;
    address?: string;
    phone?: string;
    email?: string;
    website?: string;
  };
  vehicleDetails?: {
    id?: string | number;
    label?: string;
    unitNumber?: string;
    vin?: string;
    makeModel?: string;
    licensePlate?: string;
    mileage?: string;
    year?: string;
  };
};

type StatusMap = Record<string, ChecklistStatus | undefined>;

type NotesMap = Record<string, string | undefined>;

type BusinessInfo = Required<NonNullable<RouteParams['businessInfo']>>;

type VehicleInfo = {
  id: string;
  label: string;
  unitNumber: string;
  vin: string;
  makeModel: string;
  licensePlate: string;
  mileage: string;
  year: string;
};

type PersistedChecklistDraft = {
  statusMap?: Record<string, ChecklistStatus>;
  notesMap?: NotesMap;
  inspectedBy?: string;
  inspectionDate?: string;
  additionalNotes?: string;
  businessInfo?: Partial<BusinessInfo>;
  vehicleDetails?: Partial<VehicleInfo>;
  measurements?: Partial<MeasurementMaps>;
};

const BUSINESS_INFO_KEYS = ['name', 'address', 'phone', 'email', 'website'] as const;
const VEHICLE_INFO_KEYS = ['unitNumber', 'vin', 'makeModel', 'licensePlate', 'mileage', 'year'] as const;
const VEHICLE_INFO_SNAKE_MAP: Record<(typeof VEHICLE_INFO_KEYS)[number], string> = {
  unitNumber: 'unit_number',
  vin: 'vin',
  makeModel: 'make_model',
  licensePlate: 'license_plate',
  mileage: 'mileage',
  year: 'year',
};

const sanitizeBusinessInfo = (incoming: unknown): Partial<BusinessInfo> => {
  if (!incoming || typeof incoming !== 'object') {
    return {};
  }

  const result: Partial<BusinessInfo> = {};
  BUSINESS_INFO_KEYS.forEach((key) => {
    const value = (incoming as Record<string, unknown>)[key];
    if (typeof value === 'string') {
      result[key] = value;
    }
  });

  return result;
};

const sanitizeVehicleInfo = (incoming: unknown): Partial<VehicleInfo> => {
  if (!incoming || typeof incoming !== 'object') {
    return {};
  }

  const result: Partial<VehicleInfo> = {};
  VEHICLE_INFO_KEYS.forEach((key) => {
    const source = incoming as Record<string, unknown>;
    const value = source[key] ?? source[VEHICLE_INFO_SNAKE_MAP[key]];
    if (typeof value === 'string') {
      result[key] = value;
    }
  });

  return result;
};

const sanitizeStatusMap = (incoming: unknown): StatusMap => {
  const allowed: ChecklistStatus[] = ['pass', 'fail', 'na'];
  const map: StatusMap = {};

  if (!incoming || typeof incoming !== 'object') {
    return map;
  }

  Object.entries(incoming as Record<string, unknown>).forEach(([key, value]) => {
    if (allowed.includes(value as ChecklistStatus)) {
      map[key] = value as ChecklistStatus;
    }
  });

  return map;
};

const sanitizeNotesMap = (incoming: unknown): NotesMap => {
  const map: NotesMap = {};

  if (!incoming || typeof incoming !== 'object') {
    return map;
  }

  Object.entries(incoming as Record<string, unknown>).forEach(([key, value]) => {
    if (typeof value === 'string') {
      map[key] = value;
    }
  });

  return map;
};

const sanitizeMeasurementResponse = <T extends readonly string[]>(ids: T, incoming: unknown) =>
  mergeMeasurementValues(createMeasurementMap(ids), incoming);

function statusToText(status?: ChecklistStatus) {
  if (!status) return '';
  switch (status) {
    case 'pass':
      return 'Pass';
    case 'fail':
      return 'Fail';
    case 'na':
      return 'N/A';
    default:
      return '';
  }
}

function buildChecklistHtml(
  sections: ChecklistSection[],
  statuses: StatusMap,
  notes: NotesMap,
  meta: {
    business: BusinessInfo;
    workOrderNumber?: string | number;
    jobId?: string;
    customerName?: string;
    location?: string;
    inspectionDate?: string;
    inspectedBy?: string;
    vehicle?: VehicleInfo;
    additionalNotes?: string;
    blank?: boolean;
  },
  measurements?: Partial<MeasurementMaps>,
) {
  const measurementValues: MeasurementMaps = {
    pushrodStroke: createMeasurementMap(PUSHROD_MEASUREMENT_IDS),
    treadDepth: createMeasurementMap(TREAD_DEPTH_IDS),
    tirePressure: createMeasurementMap(TIRE_PRESSURE_IDS),
  };

  if (measurements?.pushrodStroke) {
    measurementValues.pushrodStroke = mergeMeasurementValues(
      measurementValues.pushrodStroke,
      measurements.pushrodStroke,
    );
  }

  if (measurements?.treadDepth) {
    measurementValues.treadDepth = mergeMeasurementValues(
      measurementValues.treadDepth,
      measurements.treadDepth,
    );
  }

  if (measurements?.tirePressure) {
    measurementValues.tirePressure = mergeMeasurementValues(
      measurementValues.tirePressure,
      measurements.tirePressure,
    );
  }

  const rows = sections
    .map((section) => {
      const sectionRows = section.items
        .map((item) => {
          const lookup = statuses[item.id];
          const label = meta.blank ? '' : statusToText(lookup);
          const noteText = meta.blank ? '' : (notes[item.id] ?? '');
          return `
            <tr class="item-row">
              <td class="item-number">${section.code}.${item.code}</td>
              <td class="item-label">${item.label}</td>
              <td class="item-status">${label || '&mdash;'}</td>
              <td class="item-notes">${noteText ? noteText.replace(/\n/g, '<br/>') : '&mdash;'}</td>
            </tr>
          `;
        })
        .join('');

      return `
        <tr class="section-header">
          <td colspan="4">${section.code}. ${section.title}</td>
        </tr>
        ${sectionRows}
      `;
    })
    .join('');

  const formatMeasurementValue = (value?: string) => {
    if (!value) {
      return '&mdash;';
    }

    const trimmed = value.trim();
    return trimmed ? trimmed : '&mdash;';
  };

  const renderMeasurementRows = (
    layout: readonly string[][],
    labels: Record<string, string>,
    unit: string,
    values: Record<string, string>,
  ) =>
    layout
      .map(
        (row) => `
          <tr>
            ${row
              .map((key) => {
                const label = labels[key] ?? key;
                const value = values[key] ?? '';
                return `
                  <td>
                    <div class="measurement-point">
                      <div class="measurement-label">${label}<span class="measurement-unit">${unit}</span></div>
                      <div class="measurement-reading">${meta.blank ? '&mdash;' : formatMeasurementValue(value)}</div>
                    </div>
                  </td>
                `;
              })
              .join('')}
          </tr>
        `,
      )
      .join('');

  const renderTireMeasurementRows = (
    layout: readonly string[][],
    labels: Record<string, string>,
    depthUnit: string,
    depthValues: Record<string, string>,
    pressureUnit: string,
    pressureValues: Record<string, string>,
  ) =>
    layout
      .map(
        (row) => `
          <tr>
            ${row
              .map((key) => {
                const label = labels[key] ?? key;
                const depthValue = depthValues[key] ?? '';
                const pressureKey = key.replace('tire-depth', 'tire-pressure');
                const pressureValue = pressureValues[pressureKey] ?? '';
                return `
                  <td>
                    <div class="measurement-point">
                      <div class="measurement-label">${label}</div>
                      <div class="measurement-reading">Depth: <span class="measurement-unit">${depthUnit}</span> ${
                  meta.blank ? '&mdash;' : formatMeasurementValue(depthValue)
                }</div>
                      <div class="measurement-reading">Pressure: <span class="measurement-unit">${pressureUnit}</span> ${
                  meta.blank ? '&mdash;' : formatMeasurementValue(pressureValue)
                }</div>
                    </div>
                  </td>
                `;
              })
              .join('')}
          </tr>
        `,
      )
      .join('');

  const measurementSectionsHtml = `
    <tr class="section-header">
      <td colspan="4">Pushrod Stroke Measurement</td>
    </tr>
    <tr>
      <td colspan="4">
        <table class="measurement-table">
          <tbody>
            ${renderMeasurementRows(
              PUSHROD_MEASUREMENT_LAYOUT,
              PUSHROD_MEASUREMENT_LABELS,
              'in./16',
              measurementValues.pushrodStroke,
            )}
          </tbody>
        </table>
      </td>
    </tr>
    <tr class="section-header">
      <td colspan="4">Tire Depth / Pressure</td>
    </tr>
    <tr>
      <td colspan="4">
        <table class="measurement-table">
          <tbody>
            ${renderTireMeasurementRows(
              TREAD_DEPTH_LAYOUT,
              TREAD_DEPTH_LABELS,
              '/32',
              measurementValues.treadDepth,
              'psi',
              measurementValues.tirePressure,
            )}
          </tbody>
        </table>
      </td>
    </tr>
  `;

  const vehicle: Partial<VehicleInfo> = meta.vehicle ?? {};
  const business = meta.business || {};

  return `
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            margin: 32px;
            background-color: #f5f7fb;
            color: #1f2937;
          }
          .header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 24px;
          }
          .business-info {
            max-width: 55%;
          }
          .business-name {
            font-size: 28px;
            font-weight: 700;
            color: #2f63d1;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 1px;
          }
          .business-meta {
            margin: 0;
            font-size: 14px;
            line-height: 1.5;
          }
          .job-meta {
            text-align: right;
            font-size: 14px;
            line-height: 1.5;
          }
          .job-meta strong {
            color: #111827;
          }
          .title {
            font-size: 22px;
            font-weight: 700;
            color: #111827;
            margin-bottom: 12px;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(47, 99, 209, 0.08);
          }
          th {
            background: linear-gradient(120deg, #2f63d1, #2a5298);
            color: #ffffff;
            text-align: left;
            padding: 14px;
            font-size: 13px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }
          td {
            padding: 12px 14px;
            border-bottom: 1px solid #e5e7eb;
            font-size: 13px;
          }
          .section-header td {
            background: #f0f4ff;
            font-weight: 600;
            color: #1d4ed8;
            font-size: 14px;
          }
          .item-row:nth-child(even) td {
            background: #f9fafb;
          }
          .measurement-table {
            width: 100%;
            border-collapse: collapse;
            border: 1px solid #e5e7eb;
          }
          .measurement-table td {
            border: 1px solid #e5e7eb;
            padding: 12px;
          }
          .measurement-point {
            display: flex;
            flex-direction: column;
            gap: 4px;
          }
          .measurement-label {
            font-weight: 600;
            color: #1d4ed8;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }
          .measurement-unit {
            font-size: 10px;
            color: #6b7280;
            margin-left: 6px;
          }
          .measurement-reading {
            font-size: 14px;
            color: #111827;
            min-height: 20px;
          }
          .footer {
            margin-top: 24px;
            font-size: 13px;
          }
          .signature {
            margin-top: 32px;
            display: flex;
            justify-content: space-between;
            font-size: 13px;
          }
          .signature-line {
            width: 45%;
            border-top: 1px solid #9ca3af;
            padding-top: 8px;
          }
        </style>
      </head>
      <body>
        <div class="header">
          <div class="business-info">
            <div class="business-name">${business.name || 'Business Name'}</div>
            <p class="business-meta">
              ${business.address || ''}<br/>
              ${business.phone ? `Phone: ${business.phone}<br/>` : ''}
              ${business.email ? `Email: ${business.email}<br/>` : ''}
              ${business.website || ''}
            </p>
          </div>
          <div class="job-meta">
            ${meta.customerName ? `<div><strong>Customer:</strong> ${meta.customerName}</div>` : ''}
            ${meta.location ? `<div><strong>Location:</strong> ${meta.location}</div>` : ''}
            ${vehicle.unitNumber ? `<div><strong>Unit #:</strong> ${vehicle.unitNumber}</div>` : ''}
            ${vehicle.makeModel ? `<div><strong>Make/Model:</strong> ${vehicle.makeModel}</div>` : ''}
            ${vehicle.year ? `<div><strong>Year:</strong> ${vehicle.year}</div>` : ''}
            ${vehicle.vin ? `<div><strong>VIN:</strong> ${vehicle.vin}</div>` : ''}
            ${vehicle.licensePlate ? `<div><strong>Plate:</strong> ${vehicle.licensePlate}</div>` : ''}
            ${vehicle.mileage ? `<div><strong>Mileage:</strong> ${vehicle.mileage}</div>` : ''}
            ${meta.workOrderNumber ? `<div><strong>Work Order:</strong> ${meta.workOrderNumber}</div>` : ''}
            ${meta.jobId ? `<div><strong>Job ID:</strong> ${meta.jobId}</div>` : ''}
            ${scheduleCell}
          </div>
        </div>
        <div class="title">Preventive Maintenance Inspection Checklist</div>
        <table>
          <thead>
            <tr>
              <th style="width: 8%">#</th>
              <th style="width: 47%">Inspection Item</th>
              <th style="width: 17%">Status</th>
              <th style="width: 28%">Notes</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
            ${measurementSectionsHtml}
          </tbody>
        </table>
        <div class="footer">
          ${meta.inspectionDate ? `<div><strong>Inspection Date:</strong> ${meta.inspectionDate}</div>` : ''}
          ${meta.inspectedBy ? `<div><strong>Inspected By:</strong> ${meta.inspectedBy}</div>` : ''}
          ${meta.additionalNotes ? `<div style="margin-top: 12px;"><strong>Additional Notes:</strong><br/>${meta.additionalNotes.replace(/\n/g, '<br/>')}</div>` : ''}
        </div>
        <div class="signature">
          <div class="signature-line">Mechanic Signature</div>
          <div class="signature-line">Supervisor Approval</div>
        </div>
      </body>
    </html>
  `;
}

export function PmChecklistScreen() {
  const theme = useTheme();
  const route = useRoute<RouteProp<Record<string, RouteParams>, string>>();
  const navigation = useNavigation<any>();
  const params = route.params ?? {};
  const storageKey = React.useMemo(() => {
    if (params.jobId) {
      return `pm-checklist:${String(params.jobId)}`;
    }
    if (params.workOrderNumber) {
      return `pm-checklist:workorder:${String(params.workOrderNumber)}`;
    }
    return 'pm-checklist:default';
  }, [params.jobId, params.workOrderNumber]);

  const [statusMap, setStatusMap] = React.useState<StatusMap>({});
  const [notesMap, setNotesMap] = React.useState<NotesMap>({});
  const [pushrodMeasurements, setPushrodMeasurements] = React.useState<MeasurementMaps['pushrodStroke']>(() =>
    createMeasurementMap(PUSHROD_MEASUREMENT_IDS),
  );
  const [treadDepthMeasurements, setTreadDepthMeasurements] = React.useState<MeasurementMaps['treadDepth']>(() =>
    createMeasurementMap(TREAD_DEPTH_IDS),
  );
  const [tirePressureMeasurements, setTirePressureMeasurements] = React.useState<MeasurementMaps['tirePressure']>(() =>
    createMeasurementMap(TIRE_PRESSURE_IDS),
  );
  const [inspectedBy, setInspectedBy] = React.useState('');
  const [inspectionDate, setInspectionDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [additionalNotes, setAdditionalNotes] = React.useState('');
  const [historyModalVisible, setHistoryModalVisible] = React.useState(false);
  const [businessInfo, setBusinessInfo] = React.useState<BusinessInfo>(() => ({
    name: params.businessInfo?.name || 'Express Truck Lube & Repairs',
    address: params.businessInfo?.address || '2015 Vincent Massey Dr\nCornwall, ON K6H5R6',
    phone: params.businessInfo?.phone || '+1 (514) 714-9439 / +1 (613) 900-6194',
    email: params.businessInfo?.email || 'info@expresstrucklube.com',
    website: params.businessInfo?.website || 'www.expresstrucklube.com',
  }));
  // Auto-fill vehicle details from params
  const [vehicleDetails, setVehicleDetails] = React.useState<VehicleInfo>(() => {
    const details = params.vehicleDetails || {};
    return {
      id: details.id ? String(details.id) : '',
      label: details.label || '',
      unitNumber: details.unitNumber || '',
      vin: details.vin || '',
      makeModel: details.makeModel || '',
      licensePlate: details.licensePlate || '',
      mileage: details.mileage || '',
      year: details.year || '',
    };
  });

  // Update vehicle details when params change
  React.useEffect(() => {
    if (params.vehicleDetails) {
      setVehicleDetails({
        id: params.vehicleDetails.id ? String(params.vehicleDetails.id) : '',
        label: params.vehicleDetails.label || '',
        unitNumber: params.vehicleDetails.unitNumber || '',
        vin: params.vehicleDetails.vin || '',
        makeModel: params.vehicleDetails.makeModel || '',
        licensePlate: params.vehicleDetails.licensePlate || '',
        mileage: params.vehicleDetails.mileage || '',
      year: params.vehicleDetails.year || '',
    });
  }
  }, [params.vehicleDetails]);

  const vehicleHistoryId = vehicleDetails.id;
  const vehicleHistoryLabel = React.useMemo(() => {
    if (vehicleDetails.label) {
      return vehicleDetails.label;
    }
    const pieces = [vehicleDetails.unitNumber, vehicleDetails.vin].filter((value) => Boolean(value));
    if (pieces.length > 0) {
      return pieces.join(' • ');
    }
    return 'Vehicle';
  }, [vehicleDetails]);
  const [hasHydratedDraft, setHasHydratedDraft] = React.useState(false);
  const restoredFromStorageRef = React.useRef(false);
  const attemptedRemoteFetchRef = React.useRef(false);

  React.useEffect(() => {
    let isMounted = true;

    const hydrateDraft = async () => {
      setHasHydratedDraft(false);
      let restored = false;
      try {
        const stored = await AsyncStorage.getItem(storageKey);
        if (!stored || !isMounted) {
          return;
        }
        let parsed: PersistedChecklistDraft | null = null;
        try {
          parsed = JSON.parse(stored);
        } catch (error) {
          console.warn('Failed to parse saved PM checklist draft', error);
          parsed = null;
        }
        if (!parsed || typeof parsed !== 'object') {
          return;
        }

        if (typeof parsed.inspectedBy === 'string') {
          setInspectedBy(parsed.inspectedBy);
        }
        if (typeof parsed.inspectionDate === 'string') {
          setInspectionDate(parsed.inspectionDate);
        }
        if (typeof parsed.additionalNotes === 'string') {
          setAdditionalNotes(parsed.additionalNotes);
          if (parsed.additionalNotes.trim()) {
            restored = true;
          }
        }

        // Only restore business info from draft if it wasn't provided from API
        if (parsed.businessInfo && typeof parsed.businessInfo === 'object' && !params.businessInfo) {
          const sanitizedBusinessInfo = sanitizeBusinessInfo(parsed.businessInfo);
          if (Object.keys(sanitizedBusinessInfo).length > 0) {
            setBusinessInfo((prev) => ({
              ...prev,
              ...sanitizedBusinessInfo,
            }));
            restored = true;
          }
        }

        if (parsed.vehicleDetails && typeof parsed.vehicleDetails === 'object') {
          const sanitizedVehicleInfo = sanitizeVehicleInfo(parsed.vehicleDetails);
          if (Object.keys(sanitizedVehicleInfo).length > 0) {
            setVehicleDetails((prev) => ({
              ...prev,
              ...sanitizedVehicleInfo,
            }));
            restored = true;
          }
        }

        if (parsed.statusMap && typeof parsed.statusMap === 'object') {
          const sanitized = sanitizeStatusMap(parsed.statusMap);
          if (Object.keys(sanitized).length > 0) {
            setStatusMap((prev) => ({ ...prev, ...sanitized }));
            restored = true;
          }
        }

        if (parsed.notesMap && typeof parsed.notesMap === 'object') {
          const sanitizedNotes = sanitizeNotesMap(parsed.notesMap);
          if (Object.keys(sanitizedNotes).length > 0) {
            setNotesMap((prev) => ({ ...prev, ...sanitizedNotes }));
            restored = true;
          }
        }

        if (parsed.measurements && typeof parsed.measurements === 'object') {
          if (parsed.measurements.pushrodStroke && typeof parsed.measurements.pushrodStroke === 'object') {
            setPushrodMeasurements((prev) => mergeMeasurementValues(prev, parsed.measurements?.pushrodStroke));
            if (Object.keys(parsed.measurements.pushrodStroke).length > 0) {
              restored = true;
            }
          }
          if (parsed.measurements.treadDepth && typeof parsed.measurements.treadDepth === 'object') {
            setTreadDepthMeasurements((prev) => mergeMeasurementValues(prev, parsed.measurements?.treadDepth));
            if (Object.keys(parsed.measurements.treadDepth).length > 0) {
              restored = true;
            }
          }
          if (parsed.measurements.tirePressure && typeof parsed.measurements.tirePressure === 'object') {
            setTirePressureMeasurements((prev) => mergeMeasurementValues(prev, parsed.measurements?.tirePressure));
            if (Object.keys(parsed.measurements.tirePressure).length > 0) {
              restored = true;
            }
          }
        }
      } catch (error) {
        console.warn('Failed to load saved PM checklist draft', error);
      } finally {
        if (isMounted) {
          if (restored) {
            restoredFromStorageRef.current = true;
          }
          setHasHydratedDraft(true);
        }
      }
    };

    hydrateDraft();

    return () => {
      isMounted = false;
    };
  }, [storageKey]);

  React.useEffect(() => {
    if (!hasHydratedDraft) {
      return;
    }

    const payload: PersistedChecklistDraft = {
      inspectedBy,
      inspectionDate,
      additionalNotes,
      statusMap,
      notesMap,
      businessInfo,
      vehicleDetails,
      measurements: {
        pushrodStroke: pushrodMeasurements,
        treadDepth: treadDepthMeasurements,
        tirePressure: tirePressureMeasurements,
      },
    };

    AsyncStorage.setItem(storageKey, JSON.stringify(payload)).catch((error) => {
      console.warn('Failed to persist PM checklist draft', error);
    });
  }, [
    storageKey,
    hasHydratedDraft,
    inspectedBy,
    inspectionDate,
    additionalNotes,
    statusMap,
    notesMap,
    businessInfo,
    vehicleDetails,
    pushrodMeasurements,
    treadDepthMeasurements,
    tirePressureMeasurements,
  ]);

  React.useEffect(() => {
    if (!params.jobId || !hasHydratedDraft || restoredFromStorageRef.current || attemptedRemoteFetchRef.current) {
      return;
    }

    let isMounted = true;
    attemptedRemoteFetchRef.current = true;

    const loadExistingInspection = async () => {
      try {
        const response = await apiClient.get(`/jobs/${params.jobId}/pm-inspection/`);
        if (!isMounted) {
          return;
        }

        const data = response.data ?? {};

        if (typeof data.inspector_name === 'string') {
          setInspectedBy(data.inspector_name);
        }
        if (typeof data.inspection_date === 'string' && data.inspection_date) {
          setInspectionDate(data.inspection_date);
        }
        if (typeof data.additional_notes === 'string') {
          setAdditionalNotes(data.additional_notes);
        }

        if (!params.businessInfo) {
          const remoteBusiness = sanitizeBusinessInfo(data.business_info);
          if (Object.keys(remoteBusiness).length > 0) {
            setBusinessInfo((prev) => ({
              ...prev,
              ...remoteBusiness,
            }));
          }
        }

        const remoteVehicle = sanitizeVehicleInfo(data.vehicle_info);
        if (Object.keys(remoteVehicle).length > 0) {
          setVehicleDetails((prev) => ({
            ...prev,
            ...remoteVehicle,
          }));
        }

        const remoteStatuses = sanitizeStatusMap(data.status_map);
        setStatusMap(remoteStatuses);

        const remoteNotes = sanitizeNotesMap(data.notes_map);
        setNotesMap(remoteNotes);

        const measurements = data.measurements || {};
        const pushrod = sanitizeMeasurementResponse(
          PUSHROD_MEASUREMENT_IDS,
          measurements.pushrodStroke ?? measurements.pushrod_stroke,
        );
        const treadDepth = sanitizeMeasurementResponse(
          TREAD_DEPTH_IDS,
          measurements.treadDepth ?? measurements.tread_depth,
        );
        const tirePressure = sanitizeMeasurementResponse(
          TIRE_PRESSURE_IDS,
          measurements.tirePressure ?? measurements.tire_pressure,
        );
        setPushrodMeasurements(pushrod);
        setTreadDepthMeasurements(treadDepth);
        setTirePressureMeasurements(tirePressure);

        restoredFromStorageRef.current = true;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          return;
        }
        console.warn('Failed to load existing PM inspection', error);
      }
    };

    loadExistingInspection();

    return () => {
      isMounted = false;
    };
  }, [params.jobId, hasHydratedDraft, params.businessInfo]);

  const handleStatusChange = (itemId: string, value: string) => {
    setStatusMap((prev) => ({ ...prev, [itemId]: value as ChecklistStatus }));
  };

  const handlePushrodMeasurementChange = React.useCallback(
    (key: (typeof PUSHROD_MEASUREMENT_IDS)[number], value: string) => {
      setPushrodMeasurements((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleTreadDepthChange = React.useCallback(
    (key: (typeof TREAD_DEPTH_IDS)[number], value: string) => {
      setTreadDepthMeasurements((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleTirePressureChange = React.useCallback(
    (key: (typeof TIRE_PRESSURE_IDS)[number], value: string) => {
      setTirePressureMeasurements((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleSubmitInspection = async () => {
    // Validate all items have status
    const missing = CHECKLIST_SECTIONS.flatMap((section) =>
      section.items.filter((item) => !statusMap[item.id]),
    );
    if (missing.length > 0) {
      Alert.alert('Checklist Incomplete', 'Please record a status for every inspection item before submitting.');
      return;
    }

    // Validate fail items have notes
    const flaggedStatuses: ChecklistStatus[] = ['fail'];
    const flaggedWithoutNotes = CHECKLIST_SECTIONS.flatMap((section) =>
      section.items.filter((item) =>
        flaggedStatuses.includes(statusMap[item.id] as ChecklistStatus) &&
        !(notesMap[item.id] && notesMap[item.id]?.trim()),
      ),
    );
    if (flaggedWithoutNotes.length > 0) {
      Alert.alert('Add Notes', 'Please add notes for every item marked Fail.');
      return;
    }

    // Validate inspector details
    if (!inspectedBy.trim()) {
      Alert.alert('Missing Information', 'Please enter inspector name.');
      return;
    }

    try {
      // Build checklist data
      const checklist: Record<string, { status: string; notes: string }> = {};
      CHECKLIST_SECTIONS.forEach((section) => {
        section.items.forEach((item) => {
          checklist[item.id] = {
            status: statusMap[item.id] || '',
            notes: notesMap[item.id] || '',
          };
        });
      });

      // Submit to API
      const response = await apiClient.post(`/jobs/${params.jobId}/pm-inspection/submit/`, {
        business_info: businessInfo,
        vehicle_info: vehicleDetails,
        checklist,
        measurements: {
          pushrodStroke: pushrodMeasurements,
          treadDepth: treadDepthMeasurements,
          tirePressure: tirePressureMeasurements,
        },
        additional_notes: additionalNotes,
        inspector_name: inspectedBy,
        inspection_date: inspectionDate,
        customer_name: params.customerName,
        location: params.location,
      });

      // Clear draft from storage after successful submission
      await AsyncStorage.removeItem(storageKey);

      Alert.alert(
        'Success',
        'PM inspection submitted successfully! The business can now view this inspection in the work order.',
        [
          {
            text: 'OK',
            onPress: () => navigation.goBack(),
          },
        ]
      );
    } catch (error) {
      console.error('Failed to submit PM inspection:', error);
      Alert.alert('Error', 'Failed to submit inspection. Please try again.');
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: 16, backgroundColor: theme.colors.background }}>
      {/* Header Section - Similar to web template */}
      <Card style={{ marginBottom: 16, backgroundColor: '#4f46e5' }}>
        <Card.Content>
          <Text variant="headlineSmall" style={{ color: '#fff', fontWeight: 'bold', marginBottom: 4 }}>
            {businessInfo.name} PM Inspection Sheet
          </Text>
          <Text variant="bodyMedium" style={{ color: '#e0e7ff' }}>
            Preventive Maintenance Checklist
          </Text>
        </Card.Content>
      </Card>

      {/* Business & Vehicle Info - Compact Layout */}
      <Card style={{ marginBottom: 16 }}>
        <Card.Content>
          <Text variant="titleMedium" style={{ color: theme.colors.primary, marginBottom: 12, fontWeight: 'bold' }}>
            Business Information
          </Text>
          <View style={{ backgroundColor: '#f9fafb', padding: 12, borderRadius: 8, marginBottom: 8 }}>
            <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 4 }}>Business Name</Text>
            <Text variant="bodyLarge" style={{ fontWeight: '600' }}>{businessInfo.name}</Text>
          </View>
          <View style={{ backgroundColor: '#f9fafb', padding: 12, borderRadius: 8, marginBottom: 8 }}>
            <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 4 }}>Address</Text>
            <Text variant="bodyMedium">{businessInfo.address}</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 12, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 4 }}>Phone</Text>
              <Text variant="bodyMedium">{businessInfo.phone}</Text>
            </View>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 12, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 4 }}>Email</Text>
              <Text variant="bodyMedium">{businessInfo.email}</Text>
            </View>
          </View>
        </Card.Content>
      </Card>

      {/* Vehicle & Work Order Info - Compact */}
      <Card style={{ marginBottom: 16 }}>
        <Card.Content>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <Text variant="titleMedium" style={{ color: theme.colors.primary, fontWeight: 'bold' }}>
              Work Order & Vehicle Information
            </Text>
            <Button
              icon="history"
              mode="outlined"
              compact
              onPress={() => setHistoryModalVisible(true)}
              disabled={!vehicleHistoryId}
            >
              View History
            </Button>
          </View>
          <View style={{ flexDirection: 'row', gap: 8, marginBottom: 8 }}>
            <View style={{ flex: 1, backgroundColor: '#f0f9ff', padding: 10, borderRadius: 8, borderWidth: 1, borderColor: '#3b82f6' }}>
              <Text variant="bodySmall" style={{ color: '#1e40af', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Work Order #</Text>
              <Text variant="bodyLarge" style={{ fontWeight: 'bold', color: '#1e40af' }}>{params.workOrderNumber || '—'}</Text>
            </View>
            <View style={{ flex: 1, backgroundColor: '#f0fdf4', padding: 10, borderRadius: 8, borderWidth: 1, borderColor: '#22c55e' }}>
              <Text variant="bodySmall" style={{ color: '#15803d', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Job ID</Text>
              <Text variant="bodyLarge" style={{ fontWeight: 'bold', color: '#15803d' }}>{params.jobId || '—'}</Text>
            </View>
          </View>
          <View style={{ backgroundColor: '#f9fafb', padding: 10, borderRadius: 8, marginBottom: 8 }}>
            <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Customer</Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{params.customerName || '—'}</Text>
          </View>
          <View style={{ backgroundColor: '#f9fafb', padding: 10, borderRadius: 8, marginBottom: 8 }}>
            <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Location</Text>
            <Text variant="bodyMedium">{params.location || '—'}</Text>
          </View>
          <Divider style={{ marginVertical: 12 }} />
          <Text variant="titleSmall" style={{ color: theme.colors.primary, marginBottom: 8, fontWeight: 'bold' }}>
            Vehicle Details
          </Text>
          <View style={{ flexDirection: 'row', gap: 8, marginBottom: 8 }}>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 10, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Unit Number</Text>
              <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{vehicleDetails.unitNumber || '—'}</Text>
            </View>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 10, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Year</Text>
              <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{vehicleDetails.year || '—'}</Text>
            </View>
          </View>
          <View style={{ backgroundColor: '#f9fafb', padding: 10, borderRadius: 8, marginBottom: 8 }}>
            <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Make / Model</Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{vehicleDetails.makeModel || '—'}</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 10, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>VIN</Text>
              <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{vehicleDetails.vin || '—'}</Text>
            </View>
            <View style={{ flex: 1, backgroundColor: '#f9fafb', padding: 10, borderRadius: 8 }}>
              <Text variant="bodySmall" style={{ color: '#6b7280', textTransform: 'uppercase', fontSize: 10, marginBottom: 2 }}>Mileage</Text>
              <Text variant="bodyMedium" style={{ fontWeight: '600' }}>{vehicleDetails.mileage || '—'}</Text>
            </View>
          </View>
        </Card.Content>
      </Card>

      {/* Inspection Date */}
      <Card style={{ marginBottom: 16 }}>
        <Card.Content>
          <Text variant="titleMedium" style={{ color: theme.colors.primary, marginBottom: 12, fontWeight: 'bold' }}>
            Inspection Date
          </Text>
          <TextInput
            label="Date of Inspection"
            value={inspectionDate}
            onChangeText={setInspectionDate}
            mode="outlined"
          />
        </Card.Content>
      </Card>

      {/* Checklist Sections - Compact Table Style */}
      {CHECKLIST_SECTIONS.map((section, sectionIndex) => (
        <Card key={section.title} style={{ marginBottom: 16, elevation: 3 }}>
          <Card.Title
            title={`${section.code}. ${section.title}`}
            titleVariant="titleMedium"
            titleStyle={{ fontWeight: 'bold', color: '#fff' }}
            style={{ backgroundColor: '#4f46e5', paddingVertical: 8 }}
          />
          <Card.Content style={{ paddingTop: 12 }}>
            {section.items.map((item, itemIndex) => {
              const status = statusMap[item.id];
              const hasNotes = notesMap[item.id]?.trim();
              return (
                <View key={item.id} style={{ marginBottom: 12, borderBottomWidth: itemIndex < section.items.length - 1 ? 1 : 0, borderBottomColor: '#e5e7eb', paddingBottom: 12 }}>
                  <Text variant="bodyMedium" style={{ marginBottom: 8, fontWeight: '600', color: '#111827' }}>
                    {section.code}.{item.code} {item.label}
                  </Text>
                  <SegmentedButtons
                    value={status || ''}
                    onValueChange={(value) => handleStatusChange(item.id, value)}
                    buttons={[
                      { 
                        value: 'pass', 
                        label: 'Pass', 
                        style: { 
                          flex: 1,
                          backgroundColor: status === 'pass' ? '#22c55e' : 'transparent',
                        },
                        labelStyle: {
                          color: status === 'pass' ? '#ffffff' : '#22c55e',
                          fontWeight: status === 'pass' ? 'bold' : 'normal',
                        },
                      },
                      { 
                        value: 'fail', 
                        label: 'Fail', 
                        style: { 
                          flex: 1,
                          backgroundColor: status === 'fail' ? '#ef4444' : 'transparent',
                        },
                        labelStyle: {
                          color: status === 'fail' ? '#ffffff' : '#ef4444',
                          fontWeight: status === 'fail' ? 'bold' : 'normal',
                        },
                      },
                      { 
                        value: 'na', 
                        label: 'N/A', 
                        style: { 
                          flex: 1,
                          backgroundColor: status === 'na' ? '#6b7280' : 'transparent',
                        },
                        labelStyle: {
                          color: status === 'na' ? '#ffffff' : '#6b7280',
                          fontWeight: status === 'na' ? 'bold' : 'normal',
                        },
                      },
                    ]}
                  />
                  {(status === 'fail' || hasNotes) && (
                    <TextInput
                      label={status === 'fail' ? 'Notes (required)' : 'Notes'}
                      value={notesMap[item.id] || ''}
                      onChangeText={(text) => setNotesMap((prev) => ({ ...prev, [item.id]: text }))}
                      mode="outlined"
                      multiline
                      numberOfLines={2}
                      dense
                      style={{ marginTop: 8 }}
                      error={status === 'fail' && !(notesMap[item.id]?.trim())}
                      placeholder="Enter notes..."
                    />
                  )}
                </View>
              );
            })}
          </Card.Content>
        </Card>
      ))}

      {/* Measurements Section */}
      <Card style={{ marginBottom: 16, elevation: 3 }}>
        <Card.Title
          title="Brake Measurements"
          titleVariant="titleMedium"
          titleStyle={{ fontWeight: 'bold', color: '#fff' }}
          style={{ backgroundColor: '#4f46e5', paddingVertical: 8 }}
        />
        <Card.Content style={{ paddingTop: 12 }}>
          <Text variant="titleSmall" style={{ color: theme.colors.primary, marginBottom: 12, fontWeight: 'bold' }}>
            Pushrod Stroke Measurement (in./16)
          </Text>
          <View style={{ backgroundColor: '#f0f9ff', padding: 12, borderRadius: 8, marginBottom: 16 }}>
            {PUSHROD_MEASUREMENT_LAYOUT.map((row, rowIndex) => (
              <View key={`pushrod-row-${rowIndex}`} style={{ flexDirection: 'row', gap: 8, marginBottom: rowIndex < PUSHROD_MEASUREMENT_LAYOUT.length - 1 ? 8 : 0 }}>
                {row.map((key) => {
                  const typedKey = key as (typeof PUSHROD_MEASUREMENT_IDS)[number];
                  return (
                    <View key={key} style={{ flex: 1 }}>
                      <Text variant="bodySmall" style={{ marginBottom: 4, fontWeight: 'bold', color: '#1e40af', textAlign: 'center' }}>
                        {PUSHROD_MEASUREMENT_LABELS[typedKey]}
                      </Text>
                      <TextInput
                        mode="outlined"
                        value={pushrodMeasurements[typedKey]}
                        onChangeText={(value) => handlePushrodMeasurementChange(typedKey, value)}
                        keyboardType="decimal-pad"
                        placeholder="—"
                        dense
                        style={{ backgroundColor: '#fff', textAlign: 'center' }}
                      />
                    </View>
                  );
                })}
              </View>
            ))}
          </View>

          <Text variant="titleSmall" style={{ color: theme.colors.primary, marginBottom: 12, fontWeight: 'bold' }}>
            Tire Depth / Pressure
          </Text>
          <View style={{ backgroundColor: '#f0fdf4', padding: 12, borderRadius: 8 }}>
            {TREAD_DEPTH_LAYOUT.map((row, rowIndex) => (
              <View key={`tread-depth-row-${rowIndex}`} style={{ flexDirection: 'row', gap: 8, marginBottom: rowIndex < TREAD_DEPTH_LAYOUT.length - 1 ? 8 : 0 }}>
                {row.map((key) => {
                  const typedKey = key as (typeof TREAD_DEPTH_IDS)[number];
                  const pressureKey = key.replace('tire-depth', 'tire-pressure') as (typeof TIRE_PRESSURE_IDS)[number];
                  return (
                    <View key={key} style={{ flex: 1 }}>
                      <Text variant="bodySmall" style={{ marginBottom: 4, fontWeight: 'bold', color: '#15803d', textAlign: 'center' }}>
                        {TREAD_DEPTH_LABELS[typedKey]}
                      </Text>
                      <TextInput
                        mode="outlined"
                        value={treadDepthMeasurements[typedKey]}
                        onChangeText={(value) => handleTreadDepthChange(typedKey, value)}
                        keyboardType="decimal-pad"
                        placeholder="Depth (/32)"
                        dense
                        style={{ backgroundColor: '#fff', textAlign: 'center', marginBottom: 6 }}
                      />
                      <TextInput
                        mode="outlined"
                        value={tirePressureMeasurements[pressureKey]}
                        onChangeText={(value) => handleTirePressureChange(pressureKey, value)}
                        keyboardType="decimal-pad"
                        placeholder="Pressure (psi)"
                        dense
                        style={{ backgroundColor: '#fff', textAlign: 'center' }}
                      />
                    </View>
                  );
                })}
              </View>
            ))}
          </View>
        </Card.Content>
      </Card>

      {/* Additional Notes */}
      <Card style={{ marginBottom: 16 }}>
        <Card.Content>
          <Text variant="titleMedium" style={{ color: theme.colors.primary, marginBottom: 12, fontWeight: 'bold' }}>
            Additional Notes
          </Text>
          <TextInput
            label="Any additional observations or recommendations"
            value={additionalNotes}
            onChangeText={setAdditionalNotes}
            multiline
            numberOfLines={4}
            mode="outlined"
            placeholder="Enter any additional notes, recommendations, or observations here..."
            style={{ minHeight: 100 }}
          />
        </Card.Content>
      </Card>

      {/* Inspector Name - Right Above Submit Button */}
      <Card style={{ marginBottom: 16 }}>
        <Card.Content>
          <TextInput
            label="Inspected By *"
            value={inspectedBy}
            onChangeText={setInspectedBy}
            mode="outlined"
            placeholder="Enter mechanic/inspector name"
            style={{ backgroundColor: '#fffbeb', borderWidth: 1, borderColor: '#f59e0b' }}
          />
          <Text variant="bodySmall" style={{ color: '#92400e', marginTop: 4, marginLeft: 4 }}>
            * Required before submission
          </Text>
        </Card.Content>
      </Card>

      {/* Submit Button */}
      <View style={{ marginBottom: 32 }}>
        <Button
          mode="contained"
          icon="check-circle"
          onPress={handleSubmitInspection}
          style={{ backgroundColor: '#22c55e', paddingVertical: 8 }}
          labelStyle={{ fontSize: 16, fontWeight: 'bold' }}
        >
          Submit Inspection Report
        </Button>
        <Text variant="bodySmall" style={{ textAlign: 'center', color: theme.colors.onSurfaceVariant, marginTop: 8 }}>
          This will save the inspection to the work order for business review
        </Text>
      </View>
      <VehicleHistoryModal
        visible={historyModalVisible}
        vehicleId={vehicleHistoryId || null}
        vehicleLabel={vehicleHistoryLabel}
        onDismiss={() => setHistoryModalVisible(false)}
      />
    </ScrollView>
  );
}

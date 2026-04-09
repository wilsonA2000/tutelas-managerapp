/**
 * Hook compartido para polling de progreso de los 3 procesos background.
 * Elimina duplicacion entre Dashboard y ProgressModal.
 * Cada endpoint se pollea UNA sola vez con queryKey unico.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getSyncStatus, getCheckInboxStatus, getExtractionProgress } from '../services/api'

const POLL_INTERVAL = 2000 // 2s para todos los procesos

export function useSyncProgress() {
  return useQuery({
    queryKey: ['progress-sync'],
    queryFn: getSyncStatus,
    refetchInterval: POLL_INTERVAL,
  })
}

export function useGmailProgress() {
  return useQuery({
    queryKey: ['progress-gmail'],
    queryFn: getCheckInboxStatus,
    refetchInterval: POLL_INTERVAL,
  })
}

export function useExtractionProgress() {
  return useQuery({
    queryKey: ['progress-extraction'],
    queryFn: getExtractionProgress,
    refetchInterval: POLL_INTERVAL,
  })
}

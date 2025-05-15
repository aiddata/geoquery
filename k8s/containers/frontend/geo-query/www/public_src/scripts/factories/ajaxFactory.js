angular.module('aiddataDET')
  .factory('ajaxFactory', function($http, $rootScope) {

    return {

      boundaries: function () {
        return $http.post('/api/boundaries', {
          domain: $rootScope.config.domain
        });
      },

      geometry: function (geomId) {
        return $http.post('/api/geometry/' + geomId, {
          domain: $rootScope.config.domain
        });
      },

      datasets: function (boundaryId) {
        return $http.post('/api/datasets/' + boundaryId, {
          domain: $rootScope.config.domain
        });
      },

      filters: function (filterData, boundaryId) {
        var data = _.extend(_.cloneDeep(filterData), {
          boundaryId: boundaryId,
          domain: $rootScope.config.domain
        });

        return $http.post('/api/filters', data);
      },

      requests: function (searchType, searchVal) {
        return $http.post('/api/requests', {
          search_type: searchType,
          search_val: searchVal,
          domain: $rootScope.config.domain
        });
      },

      submitRequest: function (query) {
        return $http.post('/api/submit', {
          query: query,
          domain: $rootScope.config.domain
        });
      },

      info: function () {
        return $http.post('/api/info', {
          domain: $rootScope.config.domain
        });
      }

    };
  });

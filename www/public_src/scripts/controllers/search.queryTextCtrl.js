angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $state, $stateParams, queryFactory) {
  $scope.filters = queryFactory.filters;
  $scope.options = queryFactory.options;
  $scope.searchData = $state.params.dataset ? { dataset: $state.params.dataset } : {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = {};
  $scope.geography = $stateParams.boundary;
  $scope.requestData = { name: 'New Request', editing: false };

  $scope.removeFilter = function(filter, option) {
    return $scope.dataset.type === 'release' ? queryFactory.toggleFilterOff(filter, option) :
      queryFactory.toggleOptionOff(filter, option);
  };

  $scope.clearFilters = function () {
    _.chain($scope.queryStructure)
      .filter(function(param) {
        return param.optional && param.value && param.value.length;
      })
      .each(function(param) {
        return $scope.dataset.type === 'release' ? queryFactory.resetFilter(param.key) :
          queryFactory.resetOption(param.key);
      })
      .value();
  };

  // $rootScope.$on('filters:update', function(e, data) {
  //   console.log('filterupdate data', data);
  //   $scope.searchData = data;
  // });

  $rootScope.$on('filters:updated', function(e, data) {
    $scope.totals = _.pick(data, ['projects', 'locations']);

    // Being Redefined with each filters:updated event because it directly
    // references $scope vars which will need to be update
    $scope.queryStructure = setQueryStructure();
  });
  //
  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    $scope.queryStructure = setQueryStructure();
  });

  function setQueryStructure () {
    return [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.filters.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.filters.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' },
      { value: $scope.options.options.extract_types, pre: 'calculating', optional: true, key: 'options.extract_types' },
      { value: $scope.options.files, pre: 'using', optional: true, key: 'files' }
    ];
  }

  $scope.addToCart = function() {
    queryFactory.generateQuery()
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };


  $scope.$on('$viewContentLoaded', function(event) {
    $log.info('QueryTextCtrl', event);
    queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
    if ($state.params.dataset) {
      $scope.dataset = queryFactory.getDataset($state.params.dataset);
      // $scope.queryStructure = setQueryStructure();
    }
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    if (toParams.dataset) {
      $scope.dataset = queryFactory.getDataset(toParams.dataset);
      $scope.queryStructure = setQueryStructure();
    }
  });

});
